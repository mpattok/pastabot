from app import App


def main() -> None:
    app = App('builtin-cogs', 'custom-cogs')
    app.run()


if __name__ == '__main__':
    main()
