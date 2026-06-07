FALTAN POR HACER

- Cambiar el nombre del archivo que aprecen las instrucciones, que se vea en la web en lugar de radme instrucciones o asi
- Falta la logica como tal del mensaje y asi
	que agarre el numero y que mande el correo y asi
- Ver que funcione igual si es en la terminal
- Cambiar el favicon de tamaño
- Arreglar `[chainlit_app] bot.ask raised: 'Chatbot' object has no attribute 'ask'` (aparentemente es porque la función 'ask'  está indentado de una forma que queda fuera de la clase Chatbot).
- Arreglar `[chainlit_app] bot.ask raised: 'Chatbot' object has no attribute '_show_main_menu'` cuando seleccionamos 'Cancelar' (parece estar llamando una función vieja, porque solo aparece que la llaman una vez, pero no está definida en ninguna parte).
- Arreglar `[chainlit_app] bot.ask raised: 'NoneType' object has no attribute 'get'` cuando escribimos "Menú"/"Menu".