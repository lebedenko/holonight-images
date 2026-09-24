# Design

Provide separate off-by-default Clang ASan/UBSan/libFuzzer targets for raw EXIF, container metadata and bounded inspection/decoding.

Use a separate non-installed provider library instrumented with fuzzer-no-link, address and undefined sanitizers. Exercise caller-owned devices with deterministic faults and cancellation. Cap inputs at 1 MiB, RSS at 2 GiB, individual inputs at 10 seconds and each campaign at 600 seconds. Set a conservative Qt allocation ceiling before any decoding. Reuse generated fixtures and preserve seed inventories, tool versions, commands and artifacts. System codecs are not fully instrumented.
