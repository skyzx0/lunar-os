// Lunar OS default panel layout.
//
// One slim panel, floating, bottom. No task manager separator, no system
// monitor widgets, no news feed. The default desktop should be quiet; anyone
// who wants more can add it, and nobody who wants less can easily remove it.

var allPanels = panels();
for (var i = 0; i < allPanels.length; i++) {
    allPanels[i].remove();
}

var panel = new Panel("org.kde.panel");
panel.location = "bottom";
panel.height = Math.round(gridUnit * 2.4);
panel.floating = true;
panel.alignment = "center";
panel.lengthMode = "fit";

var launcher = panel.addWidget("org.kde.plasma.kickoff");
launcher.currentConfigGroup = ["Shortcuts"];
launcher.writeConfig("global", "Alt+F1");
launcher.currentConfigGroup = ["General"];
launcher.writeConfig("icon", "lunar");
launcher.writeConfig("favoritesPortedToKAstats", true);

panel.addWidget("org.kde.plasma.pager");

var tasks = panel.addWidget("org.kde.plasma.taskmanager");
tasks.currentConfigGroup = ["General"];
tasks.writeConfig("launchers", [
    "applications:systemsettings.desktop",
    "applications:org.kde.konsole.desktop"
]);
tasks.writeConfig("groupingStrategy", 1);
tasks.writeConfig("onlyGroupWhenFull", true);
tasks.writeConfig("iconOnly", true);

panel.addWidget("org.kde.plasma.marginsseparator");

var tray = panel.addWidget("org.kde.plasma.systemtray");
tray.currentConfigGroup = ["General"];
tray.writeConfig("scaleIconsToFit", true);

var clock = panel.addWidget("org.kde.plasma.digitalclock");
clock.currentConfigGroup = ["Appearance"];
clock.writeConfig("showDate", true);
clock.writeConfig("dateFormat", "isoDate");
clock.writeConfig("use24hFormat", 2);

// Desktop: plain colour, no icons. A folder view on the desktop keeps a
// directory watcher and thumbnailer alive for files nobody looks at.
var desktops = desktops();
for (var j = 0; j < desktops.length; j++) {
    desktops[j].wallpaperPlugin = "org.kde.color";
    desktops[j].currentConfigGroup = ["Wallpaper", "org.kde.color", "General"];
    desktops[j].writeConfig("Color", "10,11,13");
}
