"""Entry point for Soliq chek tahrirlash boti."""
from soliq_bot.gui import App


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
