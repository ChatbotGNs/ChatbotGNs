from chatbot import Chatbot

def main():
    bot = Chatbot()
    print("Chatbot LangChain — escribe 'salir' para terminar")

    while True:
        try:
            user = input("Tú: ")
        except (EOFError, KeyboardInterrupt):
            print("\nSaliendo...")
            break

        if not user:
            continue
        if user.strip().lower() in ("salir", "exit", "quit"):
            print("Adiós!")
            break

        try:
            reply = bot.ask(user)
        except Exception as e:
            reply = f"Error: {e}"

        print("Bot:", reply)


if __name__ == "__main__":
    main()