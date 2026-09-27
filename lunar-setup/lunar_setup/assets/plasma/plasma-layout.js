// Lunar desktop layout: a thin top bar (clock, the moon launcher in the
// middle, system tray) and a floating dock of apps at the bottom.
// New panels are built first and the old ones removed last, so a failure
// part-way leaves an extra panel rather than none.
var old = panels();

var bar = new Panel;
bar.location = "top";
bar.height = 30;
bar.addWidget("org.kde.plasma.digitalclock");
bar.addWidget("org.kde.plasma.panelspacer");
var launcher = bar.addWidget("org.kde.plasma.kickoff");
launcher.currentConfigGroup = ["General"];
launcher.writeConfig("icon", "/usr/share/lunaros/lunar-logo.svg");
bar.addWidget("org.kde.plasma.panelspacer");
bar.addWidget("org.kde.plasma.systemtray");

var dock = new Panel;
dock.location = "bottom";
dock.height = 52;
dock.floating = true;
dock.lengthMode = "fit";
dock.alignment = "center";
dock.hiding = "dodgewindows";
var tasks = dock.addWidget("org.kde.plasma.icontasks");
tasks.currentConfigGroup = ["General"];
tasks.writeConfig("launchers", [
    "applications:org.kde.dolphin.desktop",
    "applications:firefox.desktop",
    "applications:org.kde.konsole.desktop",
    "applications:org.kde.kate.desktop",
    "applications:systemsettings.desktop"
].join(","));

for (var i = 0; i < old.length; i++) {
    old[i].remove();
}
