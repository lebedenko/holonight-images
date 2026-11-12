// SPDX-License-Identifier: GPL-3.0-or-later
#include "generation.h"

#include "protocol.h"
#include "verification.h"

#include <QCryptographicHash>
#include <QFile>
#include <QFileInfo>
#include <QRegularExpression>

#include <fcntl.h>
#include <mutex>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>
#include <utility>

namespace HolonightImages {
namespace {
class Descriptor {
 public:
  explicit Descriptor(int descriptor) : fd_(descriptor) {
    if (descriptor < 0) {
      throw Isolation::ProtocolError("cannot open generation selection");
    }
  }
  ~Descriptor() {
    if (fd_ >= 0) {
      close(fd_);
    }
  }
  Descriptor(const Descriptor&) = delete;
  Descriptor& operator=(const Descriptor&) = delete;
  Descriptor(Descriptor&&) = delete;
  Descriptor& operator=(Descriptor&&) = delete;
  [[nodiscard]] int get() const { return fd_; }
  int release() { return std::exchange(fd_, -1); }

 private:
  int fd_;
};
bool same(const struct stat& left, const struct stat& right) {
  return left.st_dev == right.st_dev && left.st_ino == right.st_ino;
}
QByteArray selector(int base, struct stat& identity) {
  // POSIX openat requires a variadic declaration, including without O_CREAT.
  // NOLINTNEXTLINE(cppcoreguidelines-pro-type-vararg)
  Descriptor file(openat(base, "current", O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK));
  if (fstat(file.get(), &identity) != 0 || !S_ISREG(identity.st_mode) || identity.st_uid != 0 ||
      (identity.st_mode & 0022) != 0 || identity.st_size != 65) {
    throw Isolation::ProtocolError("invalid generation selector");
  }
  QByteArray bytes(66, '\0');
  // Owner refresh intentionally serializes selection validation. This is a
  // fixed-size regular selector opened O_NONBLOCK, never an input stream.
  // NOLINTNEXTLINE(clang-analyzer-unix.BlockInCriticalSection)
  const auto count = read(file.get(), bytes.data(), bytes.size());
  if (count != 65) {
    throw Isolation::ProtocolError("invalid generation selector size");
  }
  bytes.resize(count);
  if (!QRegularExpression("^[0-9a-f]{64}\\n$").match(QString::fromLatin1(bytes)).hasMatch()) {
    throw Isolation::ProtocolError("invalid generation basename");
  }
  bytes.chop(1);
  return bytes;
}
}  // namespace
struct GenerationLease::State {
  State() = default;
  State(const State&) = delete;
  State& operator=(const State&) = delete;
  State(State&&) = delete;
  State& operator=(State&&) = delete;
  int descriptor = -1;
  QString directory;
  QStringList binds;
  bool sessions = false;
  std::shared_ptr<std::atomic_bool> disabled;
  ~State() {
    if (descriptor >= 0) {
      close(descriptor);
    }
  }
};
struct RuntimeOwner::State {
  QString directory;
  mutable std::mutex mutex;
  GenerationLease selected;
  QString diagnostic;
  std::shared_ptr<std::atomic_bool> disabled = std::make_shared<std::atomic_bool>(false);
};
QString GenerationLease::runtimeDirectory() const { return state_ ? state_->directory : QString{}; }
bool GenerationAccess::launchAllowed(const GenerationLease& lease) { return lease && !lease.state_->disabled->load(); }
void GenerationAccess::disable(const GenerationLease& lease) {
  if (lease) {
    lease.state_->disabled->store(true);
  }
}
bool GenerationLease::supportsSessions() const { return state_ && state_->sessions; }
QStringList GenerationAccess::binds(const GenerationLease& lease) {
  if (!lease) {
    throw Isolation::ProtocolError("no validated generation lease");
  }
  return lease.state_->binds;
}
RuntimeOwner::RuntimeOwner(QString directory) : state_(std::make_unique<State>()) {
  state_->directory = std::move(directory);
  refresh();
}
RuntimeOwner::~RuntimeOwner() = default;
GenerationLease RuntimeOwner::acquire() const {
  const std::scoped_lock lock(state_->mutex);
  return state_->disabled->load() ? GenerationLease{} : state_->selected;
}
bool RuntimeOwner::launchesDisabled() const { return state_->disabled->load(); }
QString RuntimeOwner::diagnostic() const {
  const std::scoped_lock lock(state_->mutex);
  return state_->disabled->load() ? QStringLiteral("owner disabled after cleanup failure") : state_->diagnostic;
}
bool RuntimeOwner::refresh() {
  const std::scoped_lock lock(state_->mutex);
  state_->selected = {};
  state_->diagnostic.clear();
  try {
    if (state_->disabled->load()) {
      throw Isolation::ProtocolError("owner disabled after cleanup failure");
    }
    // Check the protected chain before traversing relative to pinned descriptors.
    // The inventory walk additionally rejects unprotected retained generations.
    Isolation::verifyProtectedRuntime(state_->directory);
    const auto encoded = QFile::encodeName(state_->directory);
    // POSIX no-follow descriptor acquisition uses the variadic open API.
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-vararg)
    Descriptor base(open(encoded.constData(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
    struct stat selectedIdentity{};
    const auto name = selector(base.get(), selectedIdentity);
    // POSIX no-follow descriptor acquisition uses the variadic open API.
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-vararg)
    Descriptor generations(openat(base.get(), "generations", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
    // POSIX no-follow descriptor acquisition uses the variadic open API.
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-vararg)
    Descriptor generation(openat(generations.get(), name.constData(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC));
    if (flock(generation.get(), LOCK_SH | LOCK_NB) != 0) {
      throw Isolation::ProtocolError("generation is being removed");
    }
    struct stat identity{};
    if (fstat(generation.get(), &identity) != 0) {
      throw Isolation::ProtocolError("generation identity unavailable");
    }
    const auto directory = state_->directory + "/generations/" + QString::fromLatin1(name);
    Isolation::verifyProtectedRuntime(directory);
    auto binds = Isolation::verifyRuntime(directory);
    QFile manifest(directory + "/manifest.json");
    if (!manifest.open(QIODevice::ReadOnly)) {
      throw Isolation::ProtocolError("generation manifest unavailable");
    }
    // This domain separator is part of the validation policy, shared with installation.
    const auto manifestBytes = manifest.readAll();
    const auto record = Isolation::parseControl(manifestBytes);
    const bool sessions =
        record.contains("sessionProtocol") && Isolation::integer(record, "sessionProtocol", 0, 1) == 1;
    const auto digest =
        QCryptographicHash::hash(QByteArray("holonight-images-policy-1\n") + manifestBytes, QCryptographicHash::Sha256)
            .toHex();
    if (digest != name) {
      throw Isolation::ProtocolError("generation identity does not match manifest and policy");
    }
    struct stat afterSelector{};
    struct stat afterDirectory{};
    if (selector(base.get(), afterSelector) != name || !same(selectedIdentity, afterSelector) ||
        fstatat(generations.get(), name.constData(), &afterDirectory, AT_SYMLINK_NOFOLLOW) != 0 ||
        !same(identity, afterDirectory)) {
      throw Isolation::ProtocolError("generation selection changed during validation");
    }
    GenerationLease lease;
    lease.state_ = std::make_shared<GenerationLease::State>();
    lease.state_->sessions = sessions;
    lease.state_->disabled = state_->disabled;
    lease.state_->directory = directory;
    lease.state_->binds = std::move(binds);
    lease.state_->descriptor = generation.release();
    state_->selected = std::move(lease);
    return true;
  } catch (const std::exception& error) {
    state_->diagnostic = QString::fromUtf8(error.what());
    return false;
  }
}
}  // namespace HolonightImages
