# Vendored memweave

Source: https://github.com/crypdick/memweave
Commit: 93d729a658b95fc6d78166eb2d007941c9c8e0d3
Upstream: https://github.com/sachinsharma9780/memweave
License: MIT (see LICENSE in this directory).

This is the runtime package from that commit, bundled in Obsidian Knowledge's
wheel and source distribution. It is not a separately installed dependency.
Imports use the private obsidian_knowledge_vendor.memweave namespace so this
copy cannot overwrite another application's memweave installation. The other
local adaptation replaces distribution-metadata version lookup with
its fixed source version, 0.2.1, because no separate memweave distribution exists.

To update, copy the memweave/ runtime directory and LICENSE from a reviewed
commit of the fork, retain this provenance file, relocate internal imports to the private namespace,
and reapply the version
adaptation. Copy no bytecode or caches. Update the recorded commit, synchronize
the runtime requirements in pyproject.toml with the fork's pyproject.toml, and
run the library tests plus the application's full checks and isolated wheel
installation check. Fork changes remain reviewable in the source repository.
