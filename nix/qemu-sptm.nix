# qemu-sptm — jprx's QEMU fork with the `-M darwin` machine (SPTM/TXM, XNU boot) used by
# https://github.com/jprx/darwin-vm. Built aarch64-softmmu only, with PVG disabled (as darwin-vm's README).
# The git source has no bundled meson subprojects, so the three required wraps are fetched here (pinned).
{ lib, qemu, fetchFromGitHub, fetchgit, python3Packages }:
let
  rev = "bad6336fb24211f8c4e8e946c259bd5b12417340";   # darwin-vm submodule pin (2026-10-05)
  keycodemapdb = fetchgit {
    url = "https://gitlab.com/qemu-project/keycodemapdb.git";
    rev = "f5772a62ec52591ff6870b7e8ef32482371f22c6";
    hash = "sha256-EQrnBAXQhllbVCHpOsgREzYGncMUPEIoWFGnjo+hrH4=";
  };
  softfloat = fetchgit {
    url = "https://gitlab.com/qemu-project/berkeley-softfloat-3.git";
    rev = "b64af41c3276f97f0e181920400ee056b9c88037";
    hash = "sha256-Yflpx+mjU8mD5biClNpdmon24EHg4aWBZszbOur5VEA=";
  };
  testfloat = fetchgit {
    url = "https://gitlab.com/qemu-project/berkeley-testfloat-3.git";
    rev = "e7af9751d9f9fd3b47911f51a5cfd08af256a9ab";
    hash = "sha256-inQAeYlmuiRtZm37xK9ypBltCJ+ycyvIeIYZK8a+RYU=";
  };
in
(qemu.override {
  hostCpuTargets = [ "aarch64-softmmu" ];
  guestAgentSupport = false;
  toolsOnly = false;
}).overrideAttrs (old: {
  pname = "qemu-sptm";
  version = "11.1.0-sptm-${builtins.substring 0 7 rev}";
  src = fetchFromGitHub {
    owner = "jprx";
    repo = "qemu-sptm";
    inherit rev;
    hash = "sha256-QL+fFDxlz++/hkuV6Ql4hp37YYYG6HS4wl4lVZfZUAY=";
  };
  # 11.x configure wants qemu.qmp (git sources lack the release tarball's offline wheel setup)
  nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ python3Packages.qemu-qmp python3Packages.setuptools python3Packages.pycotap python3Packages.wheel python3Packages.pip ];
  patches = [ ];      # nixpkgs' release patches target upstream tarballs, not this fork
  postPatch = (old.postPatch or "") + ''
    cp -r ${keycodemapdb} subprojects/keycodemapdb
    cp -r ${softfloat} subprojects/berkeley-softfloat-3
    cp -r ${testfloat} subprojects/berkeley-testfloat-3
    chmod -R u+w subprojects/keycodemapdb subprojects/berkeley-softfloat-3 subprojects/berkeley-testfloat-3
    cp subprojects/packagefiles/berkeley-softfloat-3/* subprojects/berkeley-softfloat-3/
    cp subprojects/packagefiles/berkeley-testfloat-3/* subprojects/berkeley-testfloat-3/
  '';
  configureFlags = (lib.filter (f: !(lib.hasPrefix "--enable-pvg" f)) (old.configureFlags or [ ])) ++ [ "--disable-pvg" ];
  # nixpkgs links qemu-kvm -> qemu-system-x86_64, which this aarch64-only build does not have
  postInstall = (old.postInstall or "") + "\n    rm -f $out/bin/qemu-kvm\n  ";
  doCheck = false;
  meta = old.meta // {
    description = "QEMU fork with the darwin machine for booting iOS/macOS kernels (jprx/qemu-sptm)";
    homepage = "https://github.com/jprx/qemu-sptm";
    mainProgram = "qemu-system-aarch64";
  };
})
