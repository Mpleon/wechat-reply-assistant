#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
[Setup]
AppId={{A9D4658F-07A2-46E2-80B1-6F107B9C3178}
AppName=Wechat Reply Assistant
AppVersion={#AppVersion}
AppPublisher=Mpleon
AppPublisherURL=https://github.com/Mpleon/wechat-reply-assistant
DefaultDirName={localappdata}\Programs\WechatReplyAssistant
DefaultGroupName=Wechat Reply Assistant
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=WechatReplyAssistant-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\WechatReplyAssistant.exe
AppMutex=Local\CodexWechatReplySingleTarget
CloseApplications=yes
[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Wechat Reply Assistant"; Filename: "{app}\WechatReplyAssistant.exe"
Name: "{autodesktop}\Wechat Reply Assistant"; Filename: "{app}\WechatReplyAssistant.exe"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Run]
Filename: "{app}\WechatReplyAssistant.exe"; Description: "Open Wechat Reply Assistant"; Flags: nowait postinstall skipifsilent
