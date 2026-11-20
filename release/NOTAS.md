## Windows setup wizard — preview 6

Choose the destination, training families, caption models, compatible test models and shortcuts in an English Windows wizard. Review the selections before downloading. For Studio alone, clear the training and caption selections. Full GPU training is outside the installer smoke test.

## Windows installer diagnostics — preview 4

The Windows installer checks that the package contains the Studio executable and required startup files, then checks them again after extraction. Errors identify the failed stage and exact missing path. An installation log is saved as `%TEMP%\HydraTrainStudio-install.log`. This helps diagnose incomplete extraction or files removed after extraction. A reported missing executable on a Windows 11 machine remains unconfirmed until its installation log is available.

This release also distributes the security and desktop updates below through both platform installers.

## Security hardening and desktop layout update

- Hardened local and external vision requests. Local services bypass environment proxies. Remote vision requires HTTPS and explicit destination confirmation. Automatic redirects are disabled to protect image payloads and credentials.
- Added response-size limits and stricter media URL validation. e621 authentication is scoped to its official API host.
- Added containment checks for imported assets, comparison manifests, checkpoint references, exports and region masks, including symbolic-link and Windows junction handling.
- Imported SQLite catalogs are copied into a clean schema. CSV exports neutralize spreadsheet formulas, and regional annotations enforce image-format, dimension and size limits.
- Project data cannot override trusted executable and external-library settings. Existing locally configured engines, ComfyUI and vision executables remain selectable in Settings.
- Training-engine archives are pinned to revisions and SHA-256 digests. Cached archives are verified before extraction. Managed engine installations use revision-specific locations. CUDA package resolution uses an explicit index order.
- Updated desktop styling, resizable work areas and compact checkpoint comparisons. Progress feedback remains accessible across workspaces.
- Added 15 security regression tests, Windows/Linux CI, static security analysis and shell syntax checks. Release builds depend on successful verification.

### Compatibility and verification

An older comparison referencing an external test model may ask you to select that model again. Previously managed training engines may require installation into the new verified location. Existing custom engine paths can be selected in Settings → Components.

All 15 security tests passed locally on Windows, including a real junction test. The updated desktop opened across six tabs, and 21 existing comparison manifests passed validation. Installer scripts passed syntax checks and release packages were built locally. Full Linux GPU execution and end-to-end training remain to be validated. These checks reduce known risks and do not establish the absence of vulnerabilities.

The CI workflow runs on pushes and pull requests. Release packaging runs when a version tag is pushed and waits for verification. This source update alone does not replace binaries in an existing release.

## Previous update — checkpoint ranking and caption hotfix

- Compare checkpoints anonymously over ten rounds. A confirmed podium awards 5, 3 and 1 points. Confirmed rounds survive a restart. Instructions are available in Portuguese, English, Spanish and Simplified Chinese.
- Choose a local test base or keep the family default. Krea2 tests use Turbo by default.
- Install optional JoyCaption Beta One in Components and associate a vision model with each caption profile. Brush annotations guide captions, and confirmed region notes can supplement training text.
- Rule34 search accepts the API credential block and reports authentication failures. Review panes resize, progress stays visible across tabs, and the footer reports available VRAM.

### Install or update

Close HydraTrainStudio and run **HydraTrainStudio-Windows.exe** on Windows x64, or run `bash HydraTrainStudio-Linux.sh` on Linux x86-64. The launcher downloads and verifies the matching application package. Existing projects and models stay in place. Linux GPU installation remains experimental.
