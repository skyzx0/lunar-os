SWAYIDLE_VERSION = 1.9.0
SWAYIDLE_SITE = $(call github,swaywm,swayidle,v$(SWAYIDLE_VERSION))
SWAYIDLE_LICENSE = MIT
SWAYIDLE_LICENSE_FILES = LICENSE
SWAYIDLE_DEPENDENCIES = host-pkgconf host-wayland wayland wayland-protocols systemd
SWAYIDLE_CONF_OPTS = -Dman-pages=disabled -Dlogind=enabled -Dlogind-provider=systemd \
	-Dzsh-completions=false -Dfish-completions=false -Dbash-completions=false

$(eval $(meson-package))
