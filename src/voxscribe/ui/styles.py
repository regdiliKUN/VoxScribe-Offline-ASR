"""QSS themes (dark by default, light available in settings)."""

DARK = """
QWidget { background: #14161b; color: #e6e9ef; font-family: 'Microsoft YaHei UI','Segoe UI',sans-serif; font-size: 13px; }
QMainWindow, QDialog { background: #14161b; }
QFrame#Card { background: #1c1f27; border: 1px solid #2c313d; border-radius: 10px; }
QLabel#Title { font-size: 20px; font-weight: 600; color: #f4f7ff; }
QLabel#Subtitle { color: #8b93a7; font-size: 12px; }
QLabel#Timer { font-size: 26px; font-weight: 600; color: #7dd3fc; }
QLabel#Hint { color: #8b93a7; }
QPushButton { background: #262b36; color: #e6e9ef; border: 1px solid #353c4b;
              border-radius: 7px; padding: 8px 14px; min-height: 30px; }
QPushButton:hover { background: #303746; border-color: #4a556b; }
QPushButton:pressed { background: #232936; }
QPushButton:disabled { background: #1c2029; color: #5c6373; border-color: #2a2f3a; }
QPushButton#Primary { background: #2563eb; border-color: #3b82f6; color: #ffffff; font-weight: 600; }
QPushButton#Primary:hover { background: #1d4ed8; }
QPushButton#Record { background: #b91c1c; border-color: #ef4444; color: #ffffff; font-weight: 600; }
QPushButton#Record:hover { background: #dc2626; }
QPushButton#Danger { background: #3f2126; border-color: #7f3540; }
QComboBox { background: #20242e; border: 1px solid #353c4b; border-radius: 6px;
            padding: 6px 10px; min-height: 28px; }
QComboBox QAbstractItemView { background: #20242e; selection-background-color: #2563eb;
                              border: 1px solid #353c4b; }
QPlainTextEdit, QTextEdit, QListWidget { background: #101319; border: 1px solid #2c313d;
                                         border-radius: 8px; padding: 10px;
                                         selection-background-color: #2563eb; }
QProgressBar { background: #20242e; border: 1px solid #2c313d; border-radius: 6px;
               height: 12px; text-align: center; }
QProgressBar::chunk { background: #3b82f6; border-radius: 5px; }
QProgressBar#Level::chunk { background: #34d399; }
QStatusBar { background: #101319; color: #8b93a7; }
QStatusBar QLabel { color: #8b93a7; }
QMenuBar { background: #14161b; color: #e6e9ef; }
QMenuBar::item:selected { background: #262b36; }
QMenu { background: #20242e; color: #e6e9ef; border: 1px solid #353c4b; }
QMenu::item:selected { background: #2563eb; }
QCheckBox, QRadioButton { spacing: 8px; }
QGroupBox { border: 1px solid #2c313d; border-radius: 8px; margin-top: 14px; padding-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #8b93a7; }
QSlider::groove:horizontal { background: #2c313d; height: 6px; border-radius: 3px; }
QSlider::handle:horizontal { background: #3b82f6; width: 14px; margin: -4px 0; border-radius: 7px; }
QTabWidget::pane { border: 1px solid #2c313d; border-radius: 8px; }
QTabBar::tab { background: #20242e; padding: 8px 16px; border: 1px solid #2c313d; }
QTabBar::tab:selected { background: #2563eb; }
"""

LIGHT = """
QWidget { background: #f5f7fb; color: #1f2430; font-family: 'Microsoft YaHei UI','Segoe UI',sans-serif; font-size: 13px; }
QFrame#Card { background: #ffffff; border: 1px solid #d9dfe9; border-radius: 10px; }
QLabel#Title { font-size: 20px; font-weight: 600; color: #111827; }
QLabel#Subtitle, QLabel#Hint { color: #667085; }
QLabel#Timer { font-size: 26px; font-weight: 600; color: #1d4ed8; }
QPushButton { background: #ffffff; color: #1f2430; border: 1px solid #d0d7e3;
              border-radius: 7px; padding: 8px 14px; min-height: 30px; }
QPushButton:hover { background: #eef2f9; }
QPushButton:disabled { color: #98a2b3; }
QPushButton#Primary { background: #2563eb; border-color: #2563eb; color: #ffffff; font-weight: 600; }
QPushButton#Record { background: #dc2626; border-color: #dc2626; color: #ffffff; font-weight: 600; }
QComboBox, QPlainTextEdit, QTextEdit, QListWidget { background: #ffffff;
              border: 1px solid #d0d7e3; border-radius: 7px; padding: 8px; }
QProgressBar { background: #e8edf5; border: 1px solid #d0d7e3; border-radius: 6px; height: 12px; text-align: center; }
QProgressBar::chunk { background: #2563eb; border-radius: 5px; }
QProgressBar#Level::chunk { background: #059669; }
QStatusBar { background: #eef2f9; color: #667085; }
"""


def stylesheet(theme: str) -> str:
    return LIGHT if theme == "light" else DARK
