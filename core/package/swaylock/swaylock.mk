SWAYLOCK_VERSION = 1.8.6
SWAYLOCK_SITE = $(call github,swaywm,swaylock,v$(SWAYLOCK_VERSION))
SWAYLOCK_LICENSE = MIT
SWAYLOCK_LICENSE_FILES = LICENSE
SWAYLOCK_DEPENDENCIES = host-pkgconf host-wayland wayland wayland-protocols libxkbcommon cairo
SWAYLOCK_CONF_OPTS = -Dman-pages=disabled -Dzsh-completions=false \
	-Dfish-completions=false -Dbash-completions=false

ifeq ($(BR2_PACKAGE_LINUX_PAM),y)
SWAYLOCK_CONF_OPTS += -Dpam=enabled
SWAYLOCK_DEPENDENCIES += linux-pam
else
SWAYLOCK_CONF_OPTS += -Dpam=disabled
SWAYLOCK_DEPENDENCIES += $(if $(BR2_PACKAGE_LIBXCRYPT),libxcrypt)
endif

ifeq ($(BR2_PACKAGE_GDK_PIXBUF),y)
SWAYLOCK_CONF_OPTS += -Dgdk-pixbuf=enabled
SWAYLOCK_DEPENDENCIES += gdk-pixbuf
else
SWAYLOCK_CONF_OPTS += -Dgdk-pixbuf=disabled
endif

$(eval $(meson-package))
