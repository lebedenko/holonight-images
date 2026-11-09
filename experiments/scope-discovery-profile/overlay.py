# SPDX-License-Identifier: GPL-3.0-or-later
"""Private exact-anchor overlays. Production decisions and IO remain unchanged."""
import difflib
import subprocess


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'overlay anchor count != 1: {old!r}')
    return text.replace(old, new)


def runtime(text):
    text = '#include "../../experiments/scope-discovery-profile/telemetry.h"\n' + text
    edits = [
        ('  if (!file.open(QIODevice::ReadOnly)) {',
         '  if (Profile::reading) Profile::readValid = false;\n  if (!file.open(QIODevice::ReadOnly)) {'),
        ('  return bytes.size() <= limit ? bytes : QByteArray{};', '''  if (Profile::reading) Profile::readValid = file.error() == QFileDevice::NoError &&
      bytes.size() < limit && bytes.endsWith('\\n');
  return bytes.size() <= limit ? bytes : QByteArray{};'''),
        ('  for (const auto& line : fileBytes(QString("/proc/%1/cgroup").arg(pid)).split(\'\\n\')) {', '''  Profile::reading = true;
  const auto bytes = fileBytes(QString("/proc/%1/cgroup").arg(pid));
  Profile::reading = false;
  const int classification = Profile::classify(bytes, unit, Profile::readValid && pid > 0);
  if (++Profile::queries > qint64(Profile::recordLimit)) Profile::failed = true;
  if (classification < 0) ++Profile::unknown;
  Profile::detail("classification", classification);
  for (const auto& line : bytes.split('\\n')) {'''),
        ('launcher_.waitForFinished(static_cast<int>(milliseconds));',
         'launcher_.waitForFinished(static_cast<int>(milliseconds)); Profile::drain(launcher_);'),
        ('    command += sandbox;', '    if (Profile::qualification) sandbox << "--profile" << Profile::fault;\n    command += sandbox;'),
        ('    process.setStandardErrorFile(QProcess::nullDevice());', '''    if (!Profile::qualification) process.setStandardErrorFile(QProcess::nullDevice());
    Profile::identity(unit);
    Profile::mark("P0");'''),
        ('    launched = true;', '    Profile::mark("P1");\n    launched = true;'),
        ('    auto check = [&] {', '''    auto check = [&] {
      Profile::drain(process);
      if (Profile::awaiting && Profile::qualification && Profile::readinessCancellation(
          Profile::fault.toStdString(), std::string_view(Profile::errors.constData(), Profile::errors.size())))
        Profile::cancellation->store(true);'''),
        ('      group = groupOf(process.processId(), unit);', '''      Profile::detail("D0");
      group = groupOf(process.processId(), unit);
      Profile::detail("D1", !group.isEmpty());
      if (!group.isEmpty()) Profile::mark("S");'''),
        ('        process.waitForFinished(5);', '''        if (++Profile::waits > qint64(Profile::recordLimit)) Profile::failed = true;
        Profile::detail("V0");
        const bool waited = process.waitForFinished(5);
        Profile::detail("V1", waited);'''),
        ('    auto receive = [&](qint64 size) {', '''    Profile::mark("L");
    if (Profile::fault == "before") { Profile::cancellation->store(true); check(); }
    auto receive = [&](qint64 size) {'''),
        ('    if (process.write("G", 1) != 1) {', '''    Profile::awaiting = true;
    if (process.write("G", 1) != 1) {'''),
        ('    result.startup = elapsed.elapsed();', '''    Profile::mark("P2");
    Profile::awaiting = false;
    result.startup = elapsed.elapsed();'''),
        ('    report = cleanup(operations, unit, group);', '''    report = cleanup(operations, unit, group);
    Profile::cleanupJson = failureDiagnostic(result.status, result.diagnostic, &*report);
    Profile::drain(process);'''),
        ('  result.elapsed = elapsed.elapsed();', '''  Profile::drain(process);
  Profile::mark("exit", process.state());
  result.elapsed = elapsed.elapsed();'''),
    ]
    for old, new in edits:
        text = replace(text, old, new)
    return text


def helper(text):
    text = '#include "../../experiments/scope-discovery-profile/telemetry.h"\n' + text
    text = replace(text, '  const std::span<char*> arguments', '''  bool qualify = false;
  const char* fault = "success";
  for (int i = 1; i + 1 < argc; ++i) if (!strcmp(argv[i], "--profile")) { qualify = true; fault = argv[i+1]; }
  const bool gate = argc > 2 && !strcmp(argv[1], "--gate");
  if (qualify) Profile::childStart(gate, true, Profile::now());
  Profile::Trailer trailer;
  const std::span<char*> arguments''')
    text = replace(text, '    execv(arguments[2], arguments.subspan(2).data());', '''    if (qualify && !strcmp(fault, "descendant")) Profile::spawnDescendant();
    execv(arguments[2], arguments.subspan(2).data());''')
    text = replace(text, '  QCoreApplication app(argc, argv);', '''  if (qualify) Profile::helperFault(fault);
  QCoreApplication app(argc, argv);''')
    return text


def apply(source, detailed):
    patches = []
    for name, transform in [('runtime', runtime), ('helper', helper)]:
        path = source / 'src/isolated' / (name + '.cpp')
        original = path.read_text()
        changed = subprocess.check_output(['clang-format', '--assume-filename='+str(path)],
                                          input=transform(original), text=True)
        path.write_text(changed)
        patches.extend(difflib.unified_diff(original.splitlines(True), changed.splitlines(True),
                                          fromfile='a/' + str(path.relative_to(source)),
                                          tofile='b/' + str(path.relative_to(source))))
    header = source / 'experiments/scope-discovery-profile/telemetry.h'
    header.write_text('#ifdef PROFILE_HELPER_BUILD\n#define PROFILE_DETAILED 0\n#else\n#define PROFILE_DETAILED ' + str(int(detailed)) + '\n#endif\n' + header.read_text())
    return ''.join(patches)
