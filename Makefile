# Lunar OS build entry points.
#
# On Arch:  make repo && make iso
# On macOS: make mac-doctor, then make mac-iso  (everything runs in a container)

PROFILE := archiso/lunar
WORK    := work
OUT     := out
UNAME   := $(shell uname -s)

.PHONY: help iso repo check clean install-deps \
        mac-doctor mac-genkey mac-image mac-check mac-repo mac-iso mac-test \
        mac-shell mac-clean

help:
	@echo "Linux host"
	@echo "  make install-deps   install archiso and build tooling"
	@echo "  make repo           build and sign every package in repo/packages"
	@echo "  make iso            build the live/install ISO"
	@echo "  make check          lint the installer and validate PKGBUILDs"
	@echo "  make clean          remove work and out directories"
	@echo
	@echo "macOS host (runs in an x86_64 Arch container)"
	@echo "  make mac-doctor     verify runtime, Rosetta, memory, gpg"
	@echo "  make mac-genkey     create the repository signing key"
	@echo "  make mac-image      build the build container"
	@echo "  make mac-check      lint without building"
	@echo "  make mac-repo       build and sign the package repository"
	@echo "  make mac-iso        build the ISO into out/"
	@echo "  make mac-test       boot the ISO in QEMU under UEFI"
	@echo "  make mac-shell      shell inside the build container"
	@echo "  make mac-clean      drop the build volume and out/"
	@echo
	@echo "Windows host"
	@echo "  make is not the entry point. Use PowerShell:"
	@echo "    .\\build\\win.ps1 doctor | genkey | image | check | repo | iso | test | shell | clean"
	@echo "  or build\\win.cmd from cmd.exe. See docs/BUILD-WINDOWS.md"
ifeq ($(UNAME),Darwin)
	@echo
	@echo "Detected macOS. Use the mac-* targets; the plain ones need Linux."
endif
ifneq (,$(findstring MINGW,$(UNAME)))
	@echo
	@echo "Detected Git Bash on Windows. Use build/win.ps1 from PowerShell instead."
endif

install-deps:
	sudo pacman -S --needed archiso git python-build python-installer \
	    python-setuptools python-wheel namcap shellcheck

repo:
	./repo/build-repo.sh

iso: repo
	sudo mkarchiso -v -w $(WORK) -o $(OUT) $(PROFILE)
	@echo
	@echo "ISO written to $(OUT)"
	@echo "Write it with: sudo dd if=$(OUT)/lunar-*.iso of=/dev/sdX bs=4M status=progress oflag=sync"

check:
	python -m compileall -q lunar-setup/lunar_setup
	shellcheck repo/build-repo.sh build/entrypoint.sh build/mac.sh || true
	@for p in repo/packages/*/PKGBUILD; do namcap "$$p" || true; done

clean:
	sudo rm -rf $(WORK) $(OUT) repo/out

mac-doctor: ; @./build/mac.sh doctor
mac-genkey: ; @./build/mac.sh genkey
mac-image:  ; @./build/mac.sh image
mac-check:  ; @./build/mac.sh check
mac-repo:   ; @./build/mac.sh repo
mac-iso:    ; @./build/mac.sh iso
mac-test:   ; @./build/mac.sh test
mac-shell:  ; @./build/mac.sh shell
mac-clean:  ; @./build/mac.sh clean
