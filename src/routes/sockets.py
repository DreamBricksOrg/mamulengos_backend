from fastapi_socketio import SocketManager

def register_socket_handlers(socket_manager: SocketManager):
    """
    Registra os eventos de SocketIO (connect, disconnect e join).
    O socket_manager deve ter sido instanciado no main.py (com app=FastAPI).
    """

    @socket_manager.on("connect")
    async def on_connect(sid, environ):
        print(f"Cliente conectado: {sid}")

    @socket_manager.on("disconnect")
    async def on_disconnect(sid):
        print(f"Cliente desconectado: {sid}")

    @socket_manager.on("join")
    async def on_join(sid, data):
        """
        Espera payload {'cod': valor}, adiciona o cliente à sala.
        Emite evento 'status' para todos na sala.
        """
        cod = data.get("cod")
        if not cod:
            return

        # Coloca esse socket (sid) na room 'cod'
        await socket_manager.enter_room(sid, cod)
        # Emite para toda a room
        await socket_manager.emit(
            "status",
            {"msg": f"Você entrou na sala {cod}"},
            room=cod
        )
