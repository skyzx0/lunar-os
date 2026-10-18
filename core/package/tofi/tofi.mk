TOFI_VERSION = 0.9.1
TOFI_SITE = $(call github,philj56,tofi,v$(TOFI_VERSION))
TOFI_LICENSE = MIT
TOFI_LICENSE_FILES = LICENSE
TOFI_DEPENDENCIES = host-pkgconf host-wayland wayland wayland-protocols libxkbcommon \
	cairo pango harfbuzz freetype libglib2
TOFI_CONF_OPTS = -Dman-pages=disabled

$(eval $(meson-package))
