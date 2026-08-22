import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import SddmComponents 2.0

/*
 * Lunar OS login.
 *
 * Black field, half moon, one input. No wallpaper, no user avatars, no
 * session carousel: a login screen is a gate, and every element that is not
 * the gate is something to look at while you are locked out.
 *
 * The moon is drawn with Canvas rather than shipped as a bitmap so it stays
 * sharp on any panel and can pick up the accent colour.
 */

Rectangle {
    id: root
    color: "#0a0b0d"

    property color fg: "#e6e9f0"
    property color muted: "#7e838f"
    property color accent: "#5ec8d8"
    property color line: "#1c1f24"

    TextConstants { id: textConstants }

    Connections {
        target: sddm
        function onLoginSucceeded() { root.state = "leaving" }
        function onLoginFailed() {
            message.text = textConstants.loginFailed
            message.color = "#e26e6e"
            password.text = ""
            password.forceActiveFocus()
            shake.start()
        }
    }

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 0
        width: 320

        // --- moon --------------------------------------------------------

        Canvas {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 92
            Layout.preferredHeight: 92

            onPaint: {
                var ctx = getContext("2d");
                ctx.reset();
                var r = width / 2;
                // Full disc, then clip away the left half. Subtracting an
                // offset disc instead would give a crescent, not a half moon.
                ctx.beginPath();
                ctx.arc(r, r, r - 2, -Math.PI / 2, Math.PI / 2, false);
                ctx.lineTo(r, r - (r - 2));
                ctx.closePath();
                ctx.fillStyle = root.fg;
                ctx.fill();
            }
        }

        Item { Layout.preferredHeight: 26 }

        Text {
            Layout.alignment: Qt.AlignHCenter
            text: "Lunar OS"
            color: root.fg
            font.pointSize: 20
            font.weight: Font.Light
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 4
            text: sddm.hostName
            color: root.muted
            font.pointSize: 9
        }

        Item { Layout.preferredHeight: 34 }

        // --- user --------------------------------------------------------

        ComboBox {
            id: user
            Layout.fillWidth: true
            Layout.preferredHeight: 40
            model: userModel
            currentIndex: userModel.lastIndex
            textRole: "name"
            // One account is the common case on a personal machine; a
            // dropdown showing a single entry is just noise.
            visible: userModel.count > 1

            background: Rectangle {
                color: "transparent"
                border.color: root.line
                border.width: 1
                radius: 6
            }
            contentItem: Text {
                leftPadding: 12
                text: user.displayText
                color: root.fg
                verticalAlignment: Text.AlignVCenter
            }
        }

        Item {
            Layout.preferredHeight: userModel.count > 1 ? 10 : 0
        }

        // --- passphrase --------------------------------------------------

        Rectangle {
            id: field
            Layout.fillWidth: true
            Layout.preferredHeight: 44
            color: "#0e1013"
            border.color: password.activeFocus ? root.accent : root.line
            border.width: 1
            radius: 6

            Behavior on border.color { ColorAnimation { duration: 120 } }

            TextInput {
                id: password
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                verticalAlignment: TextInput.AlignVCenter
                echoMode: TextInput.Password
                passwordCharacter: "•"
                passwordMaskDelay: 0
                color: root.fg
                font.pointSize: 12
                focus: true
                selectByMouse: true
                selectionColor: root.accent
                selectedTextColor: "#0a0b0d"

                onAccepted: sddm.login(user.currentText, password.text, session.currentIndex)

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Passphrase"
                    color: root.muted
                    font.pointSize: 11
                    visible: !password.text.length && !password.activeFocus
                }
            }

            SequentialAnimation {
                id: shake
                NumberAnimation { target: field; property: "x"; to: field.x - 8; duration: 45 }
                NumberAnimation { target: field; property: "x"; to: field.x + 8; duration: 45 }
                NumberAnimation { target: field; property: "x"; to: field.x; duration: 45 }
            }
        }

        Item { Layout.preferredHeight: 14 }

        Text {
            id: message
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredHeight: 16
            color: root.muted
            font.pointSize: 9
            text: ""
        }
    }

    // --- session and power, kept out of the way ---------------------------

    RowLayout {
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.margins: 20
        spacing: 16

        ComboBox {
            id: session
            model: sessionModel
            currentIndex: sessionModel.lastIndex
            textRole: "name"
            flat: true
            visible: sessionModel.rowCount() > 1
            contentItem: Text {
                text: session.displayText
                color: root.muted
                font.pointSize: 9
            }
            background: Item {}
        }

        Text {
            text: Qt.formatDateTime(new Date(), "dddd d MMMM  HH:mm")
            color: root.muted
            font.pointSize: 9
            Timer {
                interval: 30000; running: true; repeat: true
                onTriggered: parent.text = Qt.formatDateTime(new Date(), "dddd d MMMM  HH:mm")
            }
        }
    }

    RowLayout {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 20
        spacing: 18

        Text {
            text: "Suspend"
            color: suspendArea.containsMouse ? root.accent : root.muted
            font.pointSize: 9
            visible: sddm.canSuspend
            MouseArea {
                id: suspendArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: sddm.suspend()
            }
        }
        Text {
            text: "Restart"
            color: restartArea.containsMouse ? root.accent : root.muted
            font.pointSize: 9
            visible: sddm.canReboot
            MouseArea {
                id: restartArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: sddm.reboot()
            }
        }
        Text {
            text: "Shut down"
            color: powerArea.containsMouse ? root.accent : root.muted
            font.pointSize: 9
            visible: sddm.canPowerOff
            MouseArea {
                id: powerArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: sddm.powerOff()
            }
        }
    }

    states: State {
        name: "leaving"
        PropertyChanges { target: root; opacity: 0 }
    }
    transitions: Transition {
        to: "leaving"
        NumberAnimation { property: "opacity"; duration: 220 }
    }

    Component.onCompleted: password.forceActiveFocus()
}
