import platform


if platform.system() == "Darwin":
    from app_macos import FortiAutoConnApp, _install_termination_signal_handlers
    import rumps

    if __name__ == "__main__":
        rumps.events.before_start.register(_install_termination_signal_handlers)
        app = FortiAutoConnApp()
        import app_macos
        app_macos._app_instance = app
        app.run()
else:
    from windows_app import main

    if __name__ == "__main__":
        main()
