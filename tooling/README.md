# Developer tooling bundle 2.0.0

Each component has a complete checked-in copy. Python 3 is required; runtime helpers use only the standard library.
The umbrella owns canonical bundle files. Run `task tooling:sync` to copy them explicitly and
`task tooling:drift` to compare without writes. `module.json` and `dependencies.cmake` are module-specific settings;
module dependencies, languages, QML URIs, optional features, isolated test-command prefixes, and module-specific
Task/preset capabilities are permitted differences. Root formatter/tidy/clangd
files are instantiated from the templates. Source files are not automatically reformatted.

Use `task deps`, `task configure PRESET=debug`, `task build`, `task test`, `task format-check`, `task tidy`,
`task lint`, and `task check` where applicable. `debug`, `test` and `release` use `build/<preset>`; compatibility
presets remain available. Old build directories are preserved. Tests retain the module's public BUILD_TESTS or
BUILD_TESTING option. Asset workflows retain their existing validation and acceptance commands.

Only `task deps` prepares providers. `task configure`, `task build` and `task test` validate installed prerequisites
and prepared providers and never prepare source dependencies. Run `task deps` explicitly first.

Dependencies default to sibling checkouts and build under `build/deps/<module>`, installing into
`build/deps/prefix`. Set HOLONIGHT_CONFIG_SOURCE, HOLONIGHT_QT_SOURCE, HOLONIGHT_IMAGES_SOURCE,
HOLONIGHT_THUMBNAILS_SOURCE, HOLONIGHT_SEARCH_SOURCE or HOLONIGHT_SYSTEM_SERVICES_SOURCE to arbitrary local
source directories, including paths with spaces. An explicit HOLONIGHT_DEPENDENCY_PREFIX uses existing providers
without rebuilding them. Use HOLONIGHT_EXTERNAL_PREFIX for installed external libraries; normal system discovery remains available.
It is separate from the restricted internal provider prefix. Supply CMAKE_PREFIX_PATH for direct CMake use. Missing packages/sources fail with remediation;
there are no automatic downloads or global HoloNight package fallbacks. JOBS controls parallelism (default 2).

`task tooling:refresh` selects existing test compile commands before debug before release, with dependency copies
ranked below owned builds, records provenance and uncovered translation units in `.cache/tooling/coverage.json`,
and writes ignored root compile_commands.json. No builds run during refresh or doctor. Failed refresh preserves the
previous database. Compiler commands stay intact; clangd removes unsupported flags via .clangd and tidy makes a
filtered copy of the same selected database under `.cache/tooling/clang`. Qt defaults and daemon defaults are explicit
separate tidy templates; tests inherit their parent with macro/global naming exceptions.

QML editor defaults use build/test. Build it explicitly to generate qmldir and qmltypes before refresh. The portable
root .qmlls.ini disables automatic CMake calls. Refresh writes resolved machine-specific settings under
`.cache/tooling/qmlls/.qmlls.ini` and qml-paths.json. Use `task tooling:qmlls` as the editor server command for
resolved build/import paths; it passes explicit -I paths without modifying tracked defaults. Refresh also writes
an ignored JSON-compatible .serena/project.local.yml pointing Serena at the same configured wrapper. Existing
non-JSON YAML local overrides are preserved and receive a manual configuration message.
Qt tools resolve from the selected cache's Qt6_DIR; QMLLS, QMLLINT and QMLFORMAT are explicit overrides.
See [Qt configuration](https://doc.qt.io/qt-6/qtqml-tooling-qmlls.html#configuration-file).
`task tooling:doctor` reports availability, builds, imports and database coverage without installing or building.

Every component owns `.serena/project.yml`, workspace `.`, LSP languages for its current owned sources, and no
activation build command. `task serena:serve` starts Serena with the absolute module root and codex context;
`task serena:index` is an explicit indexing operation. Alternatively run
`serena start-mcp-server --project-from-cwd --context codex` inside a component. Restart the MCP process after
language/server configuration changes; activation alone does not change the process backend.
Caches, memories and project.local.yml are ignored; vendored tooling is excluded from indexing. The umbrella remains
available for cross-component work. See [Serena workflow](https://oraios.github.io/serena/02-usage/040_workflow.html).
Bash indexing requires Node.js, bash-language-server and shellcheck on PATH. Verify symbol retrieval from extensionless
`scripts/status` in Hyprlock explicitly; a running Bash server alone is not proof of recognition.

Qt package tests select qmllint from Qt6::qmllint and qml from its sibling directory or the configured Qt binary directory, without searching PATH. Set QML and QMLLINT to executable paths to override these test tools (paths with spaces are supported). Direct CMake HOLONIGHT_QML_EXECUTABLE and HOLONIGHT_QMLLINT_EXECUTABLE overrides are also supported. Automatic test-tool paths are not cached; explicit cache overrides persist. QMLLINT continues to populate the generic QMLLINT CMake variable for other modules.

External requirements live in `module.json` under `external_dependencies`. Each declaration has a stable `id`,
`scope` list (`build`, `tool`, `test`, `runtime`), optional components/version/targets and controlling `feature`.
`external_features` records explicit profile defaults. `external-packages.json` supplies discovery names and
Arch/Debian package mappings. Existing stronger consumer versions override catalog defaults. CMake remains the
authoritative compile/link check; `external.py check` uses offline CMake/pkg-config probes and never installs.

The umbrella's `tooling/modules/` contains adoption inputs for the repository work packages. They are not an
additional gitlink compatibility manifest. During adoption, copy each module's JSON and generated `.cmake` to
its own `tooling/module.json` and `tooling/dependencies.cmake`, and explicitly synchronize the shared bundle.
Standalone repositories then have all required metadata without consulting the umbrella.

Provider state records complete tracked/untracked source content, revision, compiler identity, tool versions,
build type/options, features and resolved external versions/paths. Incompatible provider build/install trees are
moved to `build/deps.previous-N`; configuration changes preserve old consumers as `build/<preset>.previous-N`.
These trees are never reused. `HOLONIGHT_PROVIDER_BUILD_TYPE` controls provider build type (default Debug).
Qt private discovery requires the selected public Qt version exactly. QML tools consume the configured import
paths and Qt tool directory.

Explicit `external_sources` overrides such as `QMARKDOWN_SOURCE` prepare a supplied local checkout into
`build/external/prefix`; no source is acquired. This development install tree stays separate from internal
providers and system deployment. A separate `HOLONIGHT_EXTERNAL_PREFIX` consumes an existing external installation.

`python3 tooling/generate-install-profile.py` generates production installer package requirements and its CMake
probe from canonical declarations. `--check` reports drift without writes. Test-only dependencies are excluded.
CI image recipes and their qualification status are recorded in the external-dependency-management initiative.

Set `HOLONIGHT_BUILD_FEATURES='BUILD_SYSTEMD=OFF'` (or other declared `OPTION=ON|OFF` values) to select a minimal
feature profile explicitly. Configure-preset boolean overrides are honored. The probe and CMake receive the same
selected values, and feature changes invalidate incompatible consumer/provider caches.

Qt package mappings expand by requested components: Core-only consumers avoid declarative/SVG packages. Nested
component switches use `features` (all listed controls must be enabled); `feature` remains the single-control form.
Compiler, compiler flags, toolchain and Qt directory overrides from configure presets are shared with prerequisite
probes and local provider preparation. Providers with a `cmake_subdirectory` prepare that standalone export only.
