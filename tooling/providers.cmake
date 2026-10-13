# SPDX-License-Identifier: GPL-3.0-or-later
# Internal providers resolve only from approved local prefixes; external packages use normal discovery.
if(HOLONIGHT_DEPENDENCY_PREFIX)
  set(_holonight_provider_prefixes "${HOLONIGHT_DEPENDENCY_PREFIX}")
elseif(CMAKE_PREFIX_PATH)
  set(_holonight_provider_prefixes "${CMAKE_PREFIX_PATH}")
  if(HOLONIGHT_EXTERNAL_PREFIX)
    list(REMOVE_ITEM _holonight_provider_prefixes "${HOLONIGHT_EXTERNAL_PREFIX}")
  endif()
else()
  set(_holonight_provider_prefixes "${CMAKE_SOURCE_DIR}/build/deps/prefix")
endif()
list(PREPEND CMAKE_PREFIX_PATH ${_holonight_provider_prefixes})
if(HOLONIGHT_EXTERNAL_PREFIX)
  list(APPEND CMAKE_PREFIX_PATH "${HOLONIGHT_EXTERNAL_PREFIX}")
endif()
list(REMOVE_DUPLICATES CMAKE_PREFIX_PATH)

function(holonight_require_provider package)
  unset(_provider_config)
  unset(_provider_config CACHE)
  find_path(_provider_config NAMES "${package}Config.cmake"
    PATHS ${_holonight_provider_prefixes}
    PATH_SUFFIXES "lib/cmake/${package}" "lib64/cmake/${package}"
      "lib/${CMAKE_LIBRARY_ARCHITECTURE}/cmake/${package}" "share/${package}/cmake"
    NO_DEFAULT_PATH NO_CACHE)
  if(NOT _provider_config)
    message(FATAL_ERROR "Missing ${package} in approved internal provider prefixes. Run task deps with supplied local sources or set HOLONIGHT_DEPENDENCY_PREFIX. No sources are downloaded.")
  endif()
  set("${package}_DIR" "${_provider_config}" CACHE PATH "Explicit local provider" FORCE)
endfunction()
