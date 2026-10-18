# Firefox, from Mozilla's own release builds.
# shellcheck shell=bash
NAME="Firefox"
DESC="Web browser by Mozilla"
HOMEPAGE="https://www.mozilla.org/firefox/"
LICENSE="MPL-2.0"

latest_version() {
    curl -fsSL https://product-details.mozilla.org/1.0/firefox_versions.json |
        jq -r .LATEST_FIREFOX_VERSION
}

install_app() {
    local v=$1
    download "https://download-installer.cdn.mozilla.net/pub/firefox/releases/$v/linux-x86_64/en-US/firefox-$v.tar.xz" firefox.tar.xz
    tar -xf firefox.tar.xz || return 1
    rm -rf /opt/firefox && mv firefox /opt/firefox || return 1
    # Updates come through ltxs upgrade, not Firefox's own updater.
    mkdir -p /opt/firefox/distribution
    cat > /opt/firefox/distribution/policies.json <<'JSON'
{ "policies": { "DisableAppUpdate": true } }
JSON
    ln -sf /opt/firefox/firefox /usr/local/bin/firefox
    cat > /usr/local/share/applications/firefox.desktop <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Firefox
Comment=Browse the web
Exec=env MOZ_ENABLE_WAYLAND=1 firefox %u
Icon=/opt/firefox/browser/chrome/icons/default/default128.png
Categories=Network;WebBrowser;
MimeType=text/html;x-scheme-handler/http;x-scheme-handler/https;
StartupWMClass=firefox
DESKTOP
}

remove_app() {
    rm -rf /opt/firefox /usr/local/bin/firefox /usr/local/share/applications/firefox.desktop
}
