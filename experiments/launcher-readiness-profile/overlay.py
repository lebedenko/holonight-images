#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact, fail-closed replacements applied only to archived disposable sources."""
import difflib


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'overlay anchor count != 1: {old!r}')
    return text.replace(old, new)


def runtime(text):
    text = '#include "../../experiments/launcher-readiness-profile/telemetry.h"\n' + text
    edits = [
        ('launcher_.waitForFinished(static_cast<int>(milliseconds));',
         'launcher_.waitForFinished(static_cast<int>(milliseconds)); Profile::drain(launcher_);'),
        ('    command += sandbox;', '    if (Profile::qualification) sandbox << "--profile" << Profile::fault;\n    command += sandbox;'),
        ('    process.setStandardErrorFile(QProcess::nullDevice());',
         '    Profile::identity(unit);\n    Profile::mark("P0", 0, true);'),
        ('    launched = true;', '    Profile::mark("P1");\n    launched = true;\n    Profile::drain(process);'),
        ('    auto check = [&] {', '''    auto check = [&] {
      Profile::drain(process);
      if (Profile::failed) throw ProtocolError("diagnostic capture exhausted");
      if (Profile::awaiting && Profile::qualification && Profile::readinessCancellation(
          Profile::fault.toStdString(), std::string_view(Profile::errors.constData(), Profile::errors.size())))
        Profile::cancellation->store(true);'''),
        ('      group = groupOf(process.processId(), unit);', '''      Profile::mark("D0");
      group = groupOf(process.processId(), unit);
      Profile::mark("D1", !group.isEmpty());
      if (!group.isEmpty()) Profile::mark("S");'''),
        ('        process.waitForFinished(5);', '''        Profile::mark("V0");
        const bool waited = process.waitForFinished(5);
        Profile::mark("V1", waited);
        Profile::drain(process);'''),
        ('    auto receive = [&](qint64 size) {', '''    Profile::mark("L");
    if (Profile::fault == "before") { Profile::cancellation->store(true); check(); }
    auto receive = [&](qint64 size) {'''),
        ('        process.waitForReadyRead(5);', '''        if (Profile::awaiting) Profile::mark("Q0");
        const bool waited = process.waitForReadyRead(5);
        if (Profile::awaiting) Profile::mark("Q1", waited);
        Profile::drain(process);'''),
        ('    if (process.write("G", 1) != 1) {', '''    Profile::mark("W0");
    const auto gateWritten = process.write("G", 1);
    Profile::mark("W1", gateWritten);
    if (gateWritten != 1) {'''),
        ('    process.waitForBytesWritten(5);\n    try {', '''    Profile::mark("W2");
    const bool gateFlushed = process.waitForBytesWritten(5);
    Profile::mark("W3", gateFlushed);
    Profile::awaiting = true;
    try {'''),
        ('    result.startup = elapsed.elapsed();', '''    Profile::mark("P2", 0, true);
    Profile::awaiting = false;
    result.startup = elapsed.elapsed();'''),
        ('    report = cleanup(operations, unit, group);', '''    report = cleanup(operations, unit, group);
    Profile::cleanupJson = failureDiagnostic(result.status, result.diagnostic, &*report);
    Profile::drain(process);'''),
        ('  result.elapsed = elapsed.elapsed();', '''  Profile::drain(process);
  Profile::mark("exit", process.state(), true);
  result.elapsed = elapsed.elapsed();'''),
    ]
    for old, new in edits:
        text = replace(text, old, new)
    return text


def helper(text):
    text = '#include "../../experiments/launcher-readiness-profile/telemetry.h"\n' + text
    text = replace(text, '  const std::span<char*> arguments', '''  const auto entry = Profile::now();
  bool qualify = false;
  const char* fault = "success";
  for (int i = 1; i + 1 < argc; ++i) if (!strcmp(argv[i], "--profile")) { qualify = true; fault = argv[i+1]; }
  const bool gate = argc > 2 && !strcmp(argv[1], "--gate");
  Profile::childStart(gate, qualify, entry);
  Profile::Trailer trailer;
  const std::span<char*> arguments''')
    text = replace(text, '    pollfd descriptor', '    Profile::child("G0");\n    pollfd descriptor')
    text = replace(text, '    execv(arguments[2], arguments.subspan(2).data());', '''    Profile::child("G1");
    if (qualify && !strcmp(fault, "descendant")) Profile::spawnDescendant();
    Profile::child("X", Profile::writeErrors);
    execv(arguments[2], arguments.subspan(2).data());''')
    text = replace(text, '  QCoreApplication app(argc, argv);', '''  if (qualify) Profile::helperFault(fault);
  QCoreApplication app(argc, argv);''')
    text = replace(text, '    if (output.write("R", 1) != 1 || !output.flush()) {', '''    Profile::child("R0");
    const auto written = output.write("R", 1);
    Profile::child("R1", written);
    bool flushed = false;
    if (written == 1) {
      Profile::child("F0");
      flushed = output.flush();
      Profile::child("F1", flushed);
    }
    if (written != 1 || !flushed) {''')
    return text


def apply(source, detailed):
    patches = []
    for name, transform in [('runtime', runtime), ('helper', helper)]:
        path = source / 'src/isolated' / (name + '.cpp')
        original = path.read_text()
        changed = transform(original)
        path.write_text(changed)
        patches.extend(difflib.unified_diff(original.splitlines(True), changed.splitlines(True),
                                          fromfile='a/' + str(path.relative_to(source)),
                                          tofile='b/' + str(path.relative_to(source))))
    # Same build options for both; only this recorded diagnostic constant differs.
    header = source / 'experiments/launcher-readiness-profile/telemetry.h'
    header.write_text('#define PROFILE_DETAILED ' + str(int(detailed)) + '\n' + header.read_text())
    return ''.join(patches)
