MAKO_VERSION = 1.11.0
MAKO_SITE = $(call github,emersion,mako,v$(MAKO_VERSION))
MAKO_LICENSE = MIT
MAKO_LICENSE_FILES = LICENSE
MAKO_DEPENDENCIES = host-pkgconf host-wayland wayland wayland-protocols cairo pango libglib2 systemd
MAKO_CONF_OPTS = -Dman-pages=disabled -Dsd-bus-provider=libsystemd

ifeq ($(BR2_PACKAGE_GDK_PIXBUF),y)
MAKO_CONF_OPTS += -Dicons=enabled
MAKO_DEPENDENCIES += gdk-pixbuf
else
MAKO_CONF_OPTS += -Dicons=disabled
endif

$(eval $(meson-package))
