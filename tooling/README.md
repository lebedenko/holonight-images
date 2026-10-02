# Developer tooling bundle 1.0.0

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

Dependencies default to sibling checkouts and build under `build/deps/<module>`, installing into
`build/deps/prefix`. Set HOLONIGHT_CONFIG_SOURCE, HOLONIGHT_QT_SOURCE, HOLONIGHT_IMAGES_SOURCE,
HOLONIGHT_THUMBNAILS_SOURCE, HOLONIGHT_SEARCH_SOURCE or HOLONIGHT_SYSTEM_SERVICES_SOURCE to arbitrary local
source directories, including paths with spaces. An explicit HOLONIGHT_DEPENDENCY_PREFIX uses existing providers
without rebuilding them. Supply CMAKE_PREFIX_PATH for direct CMake use. Missing packages/sources fail with remediation;
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
