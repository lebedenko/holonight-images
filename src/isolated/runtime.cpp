// SPDX-License-Identifier: GPL-3.0-or-later
#include "runtime.h"

#include "cleanup.h"
#include "generation.h"
#include "verification.h"

#include <QDeadlineTimer>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QProcess>
#include <QThread>
#include <QUuid>
#include <QtEndian>

#include <mutex>
#include <span>
#include <utility>
#include <vector>

namespace HolonightImages::Isolation {
namespace {
struct Failure {
  RuntimeStatus status;
  QString message;
};
QByteArray fileBytes(const QString& path, qint64 limit = controlCeiling) {
  QFile file(path);
  if (!file.open(QIODevice::ReadOnly)) {
    return {};
  }
  auto bytes = file.read(limit + 1);
  return bytes.size() <= limit ? bytes : QByteArray{};
}
QProcessEnvironment environment() {
  QProcessEnvironment env;
  env.insert("PATH", "/usr/bin");
  env.insert("LANG", "C");
  env.insert("LC_ALL", "C");
  for (const auto* key : {"XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"}) {
    if (qEnvironmentVariableIsSet(key)) {
      env.insert(key, qEnvironmentVariable(key));
    }
  }
  return env;
}
QString groupOf(qint64 pid, const QString& unit) {
  for (const auto& line : fileBytes(QString("/proc/%1/cgroup").arg(pid)).split('\n')) {
    if (line.startsWith("0::") && line.endsWith(unit.toUtf8())) {
      const auto path = QString::fromUtf8(line.mid(3));
      if (path.startsWith('/') && QDir::cleanPath(path) == path) {
        return "/sys/fs/cgroup" + path;
      }
    }
  }
  return {};
}
class NativeCleanup final : public CleanupOperations {
 public:
  explicit NativeCleanup(QProcess& launcher) : launcher_(launcher) { clock_.start(); }
  qint64 now() override { return clock_.elapsed(); }
  GroupObservation observe(const QString& group) override { return observeGroup(group); }
  int launcherState() override { return launcher_.state(); }
  void waitLauncher(qint64 milliseconds) override { launcher_.waitForFinished(static_cast<int>(milliseconds)); }
  void killLauncher() override { launcher_.kill(); }
  void pause() override { QThread::msleep(5); }
  ManagerResult manager(const QStringList& args, qint64 remaining) override {
    ManagerResult result;
    QProcess process;
    process.setProcessEnvironment(environment());
    QDeadlineTimer deadline(remaining);
    process.start("/usr/bin/systemctl", QStringList{"--user"} + args);
    result.started = process.waitForStarted(static_cast<int>(remaining));
    auto drain = [&] {
      auto append = [](QByteArray& target, const QByteArray& bytes, bool& truncated) {
        truncated = truncated || target.size() + bytes.size() > 4096;
        target += bytes.left(qMax<qsizetype>(0, 4096 - target.size()));
      };
      append(result.output, process.readAllStandardOutput(), result.output_truncated);
      append(result.errors, process.readAllStandardError(), result.errors_truncated);
    };
    while (result.started && process.state() != QProcess::NotRunning && !deadline.hasExpired()) {
      process.waitForFinished(static_cast<int>(qMin<qint64>(5, deadline.remainingTime())));
      drain();
    }
    result.timed_out = process.state() != QProcess::NotRunning;
    if (result.timed_out) {
      process.kill();
      process.waitForFinished(1);
    }
    drain();
    result.exit_code = process.exitCode();
    result.exit_status = process.exitStatus();
    result.error = process.errorString();
    return result;
  }

 private:
  QProcess& launcher_;  // NOLINT(cppcoreguidelines-avoid-const-or-ref-data-members): borrowed per-call launcher
  QElapsedTimer clock_;
};
}  // namespace

class Execution::State {
 public:
  QString runtime;
  QString resolved;
  GenerationLease held;
  QProcess process;
  QString group;
  QString unit;
  bool launched = false;
  bool session = false;
  bool prepared = false;
  bool retired = false;
  bool cleanup_verified = true;
  bool dispatched = false;
  bool active = false;
  int transaction_id = 1;
  const std::atomic_bool* cancelled = nullptr;
  QDeadlineTimer deadline;
  QElapsedTimer elapsed;
  TransportResult result;
  std::function<void()> transaction_started;
  State(QString directory, GenerationLease lease)
      : runtime(std::move(directory)), resolved(runtime), held(std::move(lease)) {
    elapsed.start();
    QObject::connect(&process, &QProcess::readyReadStandardOutput, &process, [this] {
      if (session && prepared && !active && process.bytesAvailable() != 0) {
        result.status = RuntimeStatus::ProtocolFailure;
        result.diagnostic = "unsolicited idle helper response";
        retire();
      }
    });
    QObject::connect(&process, &QProcess::finished, &process, [this] {
      if (session && prepared && !active) {
        result.status = RuntimeStatus::ProtocolFailure;
        result.diagnostic = "helper exited while idle";
        retire();
      }
    });
  }
  void check(bool observeCancellation = true) {
    if (observeCancellation && cancelled->load()) {
      throw Failure{.status = RuntimeStatus::Cancelled, .message = "cancelled"};
    }
    if (process.bytesAvailable() > byteCeiling + controlCeiling + 4) {
      throw ProtocolError("oversized helper response");
    }
    if (deadline.hasExpired()) {
      throw Failure{.status = RuntimeStatus::Timeout, .message = "15 second request deadline"};
    }
    if (!group.isEmpty()) {
      bool parsed = false;
      const auto memory = fileBytes(group + "/memory.peak").trimmed().toLongLong(&parsed);
      if (parsed) {
        result.peak_memory = qMax(result.peak_memory, memory);
      }
    }
  }
  QByteArray receive(qint64 size) {
    QByteArray bytes;
    while (bytes.size() < size) {
      check();
      if (process.bytesAvailable() > byteCeiling + controlCeiling + 4) {
        throw ProtocolError("oversized helper response");
      }
      auto part = process.read(qMin<qint64>(65536, size - bytes.size()));
      bytes += part;
      if (bytes.size() == size) {
        break;
      }
      if (process.state() == QProcess::NotRunning && process.bytesAvailable() == 0) {
        throw ProtocolError("helper EOF");
      }
      process.waitForReadyRead(5);
    }
    return bytes;
  }
  void send(const QByteArray& segment) {
    qint64 sent = 0;
    while (sent < segment.size() || (process.bytesToWrite() != 0)) {
      check();
      if (sent < segment.size() && process.bytesToWrite() < 65536) {
        const auto written = process.write(std::span<const char>(segment).subspan(sent).data(),
                                           qMin<qint64>(65536, segment.size() - sent));
        if (written < 0) {
          throw ProtocolError("helper write failed");
        }
        if (!dispatched && written > 0) {
          dispatched = true;
          if (session && transaction_started) {
            transaction_started();
          }
        }
        sent += written;
      }
      process.waitForBytesWritten(5);
      if (process.state() == QProcess::NotRunning) {
        throw ProtocolError("helper exited during request");
      }
    }
  }
  // Keep scope ownership, limits and trusted gate release in security order.
  // NOLINTNEXTLINE(readability-function-cognitive-complexity)
  void launch() {
    QStringList binds;
    try {
      if (!held && QFileInfo::exists(runtime + "/current")) {
        RuntimeOwner owner(runtime);
        held = owner.acquire();
        if (!held) {
          throw ProtocolError(owner.diagnostic().toStdString());
        }
      }
      if (held) {
        if (!GenerationAccess::launchAllowed(held)) {
          throw ProtocolError("owner disabled after cleanup failure");
        }
        resolved = held.runtimeDirectory();
        binds = GenerationAccess::binds(held);
      } else {
        binds = verifyRuntime(runtime);
      }
    } catch (const std::exception& e) {
      throw Failure{.status = RuntimeStatus::Unavailable, .message = QString::fromUtf8(e.what())};
    }
    if (cancelled->load()) {
      throw Failure{.status = RuntimeStatus::Cancelled, .message = "cancelled before launch"};
    }
    for (const auto* tool : {"/usr/bin/bwrap", "/usr/bin/systemd-run", "/usr/bin/systemctl"}) {
      if (!QFileInfo(tool).isExecutable()) {
        throw Failure{.status = RuntimeStatus::Unavailable, .message = "missing runtime launcher"};
      }
    }
    unit = "holonight-images-" + QUuid::createUuid().toString(QUuid::Id128) + ".scope";
    QStringList sandbox{"/usr/bin/bwrap",
                        "--unshare-all",
                        "--die-with-parent",
                        "--new-session",
                        "--clearenv",
                        "--setenv",
                        "PATH",
                        "/usr/bin",
                        "--setenv",
                        "HOME",
                        "/tmp",
                        "--setenv",
                        "QT_PLUGIN_PATH",
                        "/usr/lib/qt6/plugins",
                        "--setenv",
                        "QT_IMAGEIO_MAXALLOC",
                        QString::number(qtAllocationMiB),
                        "--proc",
                        "/proc",
                        "--dev",
                        "/dev",
                        "--tmpfs",
                        "/tmp",
                        "--dir",
                        "/run",
                        "--dir",
                        "/usr/lib",
                        "--symlink",
                        "usr/lib",
                        "/lib",
                        "--symlink",
                        "usr/lib",
                        "/lib64"};
    sandbox += binds;
    sandbox << "--remount-ro" << "/" << "--" << "/usr/libexec/holonight-images-helper";
    if (session) {
      sandbox << "--session";
    }
    QStringList command{"--user",
                        "--scope",
                        "--quiet",
                        "--unit=" + unit,
                        "--property=MemoryMax=" + QString::number(scopeMemoryCeiling),
                        "--property=MemorySwapMax=" + QString::number(scopeSwapCeiling),
                        resolved + "/usr/libexec/holonight-images-helper",
                        "--gate"};
    command += sandbox;
    process.setUnixProcessParameters(
        {.flags = QProcess::UnixProcessFlag::CloseFileDescriptors | QProcess::UnixProcessFlag::CreateNewSession,
         .lowestFileDescriptorToClose = 3});
    process.setProcessEnvironment(environment());
    process.setStandardErrorFile(QProcess::nullDevice());
    deadline = QDeadlineTimer(15000);
    process.start("/usr/bin/systemd-run", command);
    if (!process.waitForStarted(1000)) {
      throw Failure{.status = RuntimeStatus::Unavailable, .message = "launcher failed to start"};
    }
    launched = true;
    while (group.isEmpty()) {
      // Once systemd-run has started, establish ownership before observing
      // cancellation. The trusted gate cannot consume image input meanwhile.
      // Otherwise cancellation can race scope creation and leave retirement
      // without an identity to prove empty. The startup deadline still applies.
      check(false);
      group = groupOf(process.processId(), unit);
      if (process.state() == QProcess::NotRunning) {
        throw Failure{.status = RuntimeStatus::Unavailable, .message = "scope startup failed"};
      }
      if (group.isEmpty()) {
        process.waitForFinished(5);
      }
    }
    check();
    if (fileBytes(group + "/memory.max").trimmed() != QByteArray::number(scopeMemoryCeiling) ||
        fileBytes(group + "/memory.swap.max").trimmed() != QByteArray::number(scopeSwapCeiling)) {
      throw Failure{.status = RuntimeStatus::Unavailable, .message = "scope limits not enforced"};
    }
    if (process.write("G", 1) != 1) {
      throw ProtocolError("launcher gate write failed");
    }
    process.waitForBytesWritten(5);
    try {
      if (receive(1) != "R") {
        throw ProtocolError("missing helper readiness");
      }
    } catch (const ProtocolError&) {
      throw Failure{.status = RuntimeStatus::Unavailable, .message = "sandbox helper failed before readiness"};
    }
    if (session) {
      const auto length = qFromBigEndian<quint32>(receive(4).constData());
      if (length == 0 || length > controlCeiling) {
        throw ProtocolError("readiness control limit");
      }
      const auto ready = parseControl(receive(length));
      integer(ready, "sessionVersion", 1, 1);
      if (ready.size() != 2 || ready["command"] != "ready") {
        throw ProtocolError("invalid session readiness");
      }
    }
    result.startup = elapsed.elapsed();
    result.status = RuntimeStatus::Success;
    prepared = true;
  }
  // Keep wire sequencing and completion validation in transaction order.
  // NOLINTNEXTLINE(readability-function-cognitive-complexity)
  void transact(const Request& request, const QByteArray& input, const TransactionCoordinator& coordinate) {
    int sequence = 0;
    dispatched = false;
    if (held && !GenerationAccess::launchAllowed(held)) {
      throw Failure{.status = RuntimeStatus::Unavailable, .message = "owner disabled after cleanup failure"};
    }
    if (transaction_id == INT_MAX) {
      throw ProtocolError("session transaction identity exhausted");
    }
    deadline = QDeadlineTimer(15000);
    const auto operationStart = elapsed.elapsed();
    process.waitForReadyRead(0);  // Include bytes still in the pipe, not only Qt's buffer.
    if (process.bytesAvailable() != 0) {
      throw ProtocolError("trailing response before transaction");
    }
    int candidates = 0;
    bool sourceDecoded = false;
    std::exception_ptr transactionFailure;
    auto exchange = [&](const Request& command, const QByteArray& data, bool retained) {
      try {
        if (transactionFailure) {
          std::rethrow_exception(transactionFailure);
        }
        check();
        if (sequence > 0 &&
            (command.operation != Operation::Decode || sourceDecoded || (!retained && ++candidates > 4))) {
          throw ProtocolError("invalid transaction command sequence");
        }
        if (retained) {
          sourceDecoded = true;
        }
        auto record = requestControl(command, data.size());
        if (coordinate) {
          record["transactionVersion"] = 1;
          record["sequence"] = sequence;
          record["retainedSource"] = retained;
        }
        if (session) {
          record["sessionVersion"] = 1;
          record["transactionId"] = transaction_id;
        }
        send(frame(record));
        send(data);
        const auto length = qFromBigEndian<quint32>(receive(4).constData());
        if ((length == 0U) || length > controlCeiling) {
          throw ProtocolError("response control limit");
        }
        const auto control = parseControl(receive(length));
        if (coordinate) {
          integer(control, "transactionVersion", 1, 1);
          integer(control, "sequence", sequence, sequence);
        }
        if (session) {
          integer(control, "sessionVersion", 1, 1);
          integer(control, "transactionId", transaction_id, transaction_id);
        }
        const auto bytes = integer(control, "bytes", 0, qMin(byteCeiling, command.options.limits.decodedBytes));
        auto reply = parseReply(control, receive(bytes), command);
        check();
        ++sequence;
        return reply;
      } catch (...) {
        transactionFailure = std::current_exception();
        throw;
      }
    };
    auto reply = exchange(request, input, false);
    if (coordinate) {
      auto selected = coordinate(reply.inspection, exchange);
      if (transactionFailure) {
        std::rethrow_exception(transactionFailure);
      }
      check();
      selected.inspection = reply.inspection;
      reply.decoded = std::move(selected);
    }
    check();  // Sample the final peak while the helper is still waiting for acknowledgement.
    result.operation = elapsed.elapsed() - operationStart;
    if (session) {
      send(frame(QJsonObject{
          {"sessionVersion", 1}, {"transactionId", transaction_id}, {"sequence", sequence}, {"command", "complete"}}));
      const auto length = qFromBigEndian<quint32>(receive(4).constData());
      if (length == 0 || length > controlCeiling) {
        throw ProtocolError("completion control limit");
      }
      const auto completion = parseControl(receive(length));
      integer(completion, "sessionVersion", 1, 1);
      integer(completion, "transactionId", transaction_id, transaction_id);
      integer(completion, "sequence", sequence, sequence);
      if (completion.size() != 4 || completion["command"] != "completed" || process.bytesAvailable() != 0) {
        throw ProtocolError("invalid transaction completion acknowledgement");
      }
      check();
      ++transaction_id;
      result.reply = std::move(reply);
      result.status = RuntimeStatus::Success;
      return;
    }
    if (process.write("A", 1) != 1) {
      throw ProtocolError("helper acknowledgement failed");
    }
    process.closeWriteChannel();
    while (process.state() != QProcess::NotRunning) {
      check();
      if (process.bytesAvailable() != 0) {
        throw ProtocolError("trailing response");
      }
      process.waitForFinished(5);
    }
    if ((process.bytesAvailable() != 0) || process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0) {
      throw ProtocolError("helper failed or trailing response");
    }
    check();
    result.reply = std::move(reply);
    result.status = RuntimeStatus::Success;
  }
  template <class Operation>
  void attempt(Operation operation) {
    try {
      operation();
    } catch (const Failure& error) {
      result.status = error.status;
      result.diagnostic = error.message;
    } catch (const std::exception& error) {
      result.status = RuntimeStatus::ProtocolFailure;
      result.diagnostic = QString::fromUtf8(error.what());
    } catch (...) {
      result.status = RuntimeStatus::ProtocolFailure;
      result.diagnostic = "non-standard transaction exception";
    }
  }
  void retire() {
    if (retired) {
      return;
    }
    retired = true;
    prepared = false;
    // No reply is valid after retirement begins. Closing the read side also
    // prevents a compromised idle worker from growing the parent's Qt buffer.
    process.closeReadChannel(QProcess::StandardOutput);
    process.closeWriteChannel();
    const auto original = result.status;
    const auto diagnostic = result.diagnostic;
    std::optional<CleanupReport> report;
    if (launched) {
      NativeCleanup operations(process);
      report = cleanup(operations, unit, group);
    }
    finishCleanup(result, original, diagnostic, report ? &*report : nullptr, cancelled != nullptr && cancelled->load());
    if (report && !report->verified) {
      cleanup_verified = false;
      GenerationAccess::disable(held);
    }
    result.elapsed = elapsed.elapsed();
  }
};
Execution::Execution(QString runtime, GenerationLease lease)
    : state_(std::make_unique<State>(std::move(runtime), std::move(lease))) {}
void Execution::dispose() {
  if (!state_) {
    return;
  }
  state_->cancelled = nullptr;
  state_->retire();
  if (!state_->cleanup_verified) {
    // Keep both Qt's launcher and the lease until process exit. Destroying a
    // running QProcess would issue another kill/wait outside the cleanup budget.
    // This process-held quarantine is intentionally never destroyed or retried.
    static std::mutex mutex;
    static auto* const quarantine = new std::vector<std::unique_ptr<State>>;
    const std::scoped_lock lock(mutex);
    quarantine->push_back(std::move(state_));
  } else {
    state_.reset();
  }
}
Execution::~Execution() { dispose(); }
Execution::Execution(Execution&&) noexcept = default;
Execution& Execution::operator=(Execution&& other) noexcept {
  if (this != &other) {
    dispose();
    state_ = std::move(other.state_);
  }
  return *this;
}
void Execution::setTransactionStartedCallback(std::function<void()> callback) {
  state_->transaction_started = std::move(callback);
}
TransportResult Execution::prepare(const std::atomic_bool& cancelled, bool reusable) {
  if (state_->prepared || state_->retired) {
    return {.status = RuntimeStatus::Unavailable, .reply = {}, .diagnostic = "execution already prepared or retired"};
  }
  state_->cancelled = &cancelled;
  state_->session = reusable;
  state_->attempt([&] {
    if (reusable && (!state_->held || !state_->held.supportsSessions())) {
      throw Failure{.status = RuntimeStatus::Unavailable,
                    .message = "reusable execution requires a session-capable generation lease"};
    }
    state_->launch();
  });
  if (state_->result.status != RuntimeStatus::Success) {
    state_->retire();
  }
  state_->cancelled = nullptr;
  return state_->result;
}
TransportResult Execution::transaction(const Request& request, const QByteArray& input,
                                       const std::atomic_bool& cancelled, const TransactionCoordinator& coordinate) {
  state_->result.reply.reset();
  state_->result.diagnostic.clear();
  state_->cancelled = &cancelled;
  if (!state_->prepared || state_->retired) {
    state_->result.status = RuntimeStatus::Unavailable;
    state_->result.diagnostic = "session is not ready";
  } else if (cancelled.load()) {
    // No command reached the wire; readiness survives this cancellation.
    state_->result.status = RuntimeStatus::Cancelled;
  } else {
    state_->active = true;
    state_->attempt([&] { state_->transact(request, input, coordinate); });
    state_->active = false;
    if (!state_->session || (state_->result.status != RuntimeStatus::Success &&
                             (state_->result.status != RuntimeStatus::Cancelled || state_->dispatched))) {
      state_->retire();
    }
  }
  state_->result.elapsed = state_->elapsed.elapsed();
  auto result = state_->result;
  state_->result.reply.reset();
  state_->cancelled = nullptr;
  return result;
}
TransportResult Execution::retire() {
  state_->cancelled = nullptr;
  state_->result.reply.reset();
  state_->retire();
  return state_->result;
}
bool Execution::ready() const { return state_ && state_->prepared && !state_->retired; }
qint64 Execution::idleMemory() const {
  if (!ready()) {
    return 0;
  }
  bool parsed = false;
  const auto bytes = fileBytes(state_->group + "/memory.current").trimmed().toLongLong(&parsed);
  return parsed && bytes >= 0 ? bytes : -1;
}
TransportResult dispatch(const QString& runtime, const Request& request, const QByteArray& input,
                         const std::atomic_bool& cancelled, const TransactionCoordinator& coordinate,
                         const GenerationLease& generation) {
  Execution execution(runtime, generation);
  auto prepared = execution.prepare(cancelled, false);
  if (prepared.status != RuntimeStatus::Success) {
    return prepared;
  }
  return execution.transaction(request, input, cancelled, coordinate);
}
}  // namespace HolonightImages::Isolation
