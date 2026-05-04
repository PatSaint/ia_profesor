# ia_profesor

Asistente web para practicar inglés con memoria persistente, entrada por texto o micrófono, voz de respuesta opcional y selección de múltiples IAs.

## Finalidad

`ia_profesor` está pensado como un profesor/coach de inglés accesible desde el navegador.

Sirve para:
- practicar inglés escrito o hablado
- recibir correcciones y explicaciones
- mantener conversaciones con memoria entre sesiones
- elegir con qué IA querés hablar
- usarlo localmente o compartirlo en tu red local

## Cómo funciona

La app corre en tu máquina con Flask y abre una interfaz web tipo chat.

Flujo general:
1. escribís o hablás
2. si hablás, Whisper transcribe el audio
3. la IA elegida genera la respuesta
4. la respuesta aparece en texto
5. opcionalmente se genera audio TTS y se reproduce

La memoria de chats y la configuración local se guardan en:

```text
chat_data/
```

## Lo más importante

- interfaz web tipo chat
- múltiples chats persistentes
- recordar el último chat y continuar después
- selector de IA y modelo
- soporte para texto + micrófono
- audio de respuesta en modo automático o manual
- reproducción individual por mensaje con botón 🔊
- launcher local y launcher LAN

---

## Proveedores de IA soportados

### 1. OpenAI Web/Login

Conexión por navegador inspirada en OpenCode.

Qué hace:
- login con tu cuenta ChatGPT desde navegador
- guarda tokens localmente
- refresca tokens automáticamente
- usa requests compatibles con el flujo Codex/ChatGPT

Importante:
- depende de los límites reales de tu cuenta OpenAI
- si OpenAI responde con `429 usage_limit_reached`, no es bug de la app: es límite/cuota de la cuenta

### 2. OpenAI API

Conexión por API key oficial.

Qué hace:
- lista modelos desde OpenAI
- permite activarlos desde la UI
- no depende del login web

### 3. Gemini API

Conexión por API key de Google/Gemini.

Qué hace:
- lista modelos compatibles con `generateContent`
- permite activarlos desde la UI

### 4. Ollama

Modo local opcional.

Qué hace:
- usa modelos locales vía Ollama
- puede apuntar a tu máquina o a otra PC de la red

### 5. Self-hosted / Local / Red

Además de Ollama, podés agregar múltiples servidores propios.

Ejemplos:
- Ollama local: `http://127.0.0.1:11434`
- Ollama en otra laptop: `http://192.168.1.50:11434`
- LM Studio: `http://127.0.0.1:1234/v1`
- cualquier servidor OpenAI-compatible custom

Podés guardar varios y después elegirlos desde la lista de IAs.

---

## Instalación simple en Windows

Archivos principales de instalación:

- `install.bat`
- `install.ps1`

### Qué hace el instalador

- clona el repo en una carpeta nueva
- verifica Git y Python
- crea `.venv`
- instala dependencias Python
- crea acceso directo en el escritorio:

```text
Iniciar ia_profesor
```

### Nota sobre Ollama

Ollama **ya no es obligatorio**.

El instalador ahora:
- detecta si existe
- pregunta si querés instalarlo para modo local
- si no querés, igual deja la app funcional para OpenAI/Gemini y otros providers remotos

---

## Archivos `.bat` importantes

### `web.bat`

Abre la app en modo local.

Uso típico:

```bat
web.bat
```

Qué hace:
- reinicia la instancia si ya había algo en el puerto 5000
- lanza la app para uso en la misma máquina
- abre una pantalla de espera y luego entra a la web cuando ya terminó de cargar

### `web_server.bat`

Abre la app en modo **LAN** para entrar desde otro equipo, por ejemplo tu celular.

Uso:

```bat
web_server.bat
```

Qué hace:
- levanta la app en `0.0.0.0:5000`
- intenta verificar/crear regla de firewall
- muestra en consola URLs tipo:

```text
http://192.168.x.x:5000
```

para entrar desde otros equipos de la misma red

### `Iniciar ia_profesor.bat`

Launcher pensado para usuario final.

Qué hace:
- intenta actualizar el repo automáticamente
- prepara dependencias
- si hay Ollama, lo prepara
- si no hay Ollama, sigue igual
- abre la app

---

## Modos de audio de respuesta

En la UI existe el selector:

```text
¿Escuchar respuestas?
```

Opciones:

### Automático
- primero aparece el texto
- después genera y reproduce el audio

### Manual
- aparece solo el texto
- no genera audio automáticamente
- podés reproducir cualquier mensaje del coach con el botón 🔊

---

## Cosas a tener en cuenta

- `chat_data/` guarda memoria local, providers y tokens
- `openai_web_auth.json` queda dentro de `chat_data/`
- esas credenciales son locales y no deberían versionarse
- si un provider remoto falla, la UI puede mostrar el error real del proveedor
- si OpenAI Web dice `usage_limit_reached`, significa que tu cuenta llegó al límite temporal

---

## Estructura principal

- `web_app.py` — servidor Flask
- `templates/index.html` — interfaz web
- `conversation_manager.py` — chats persistentes
- `provider_manager.py` — selección y conexión de IAs
- `openai_web_auth.py` — login web de OpenAI
- `install.ps1` / `install.bat` — instalador Windows
- `launch.ps1` — launcher principal
- `web.bat` — modo local
- `web_server.bat` — modo LAN

---

## Estado actual

El proyecto ya está orientado a:
- uso web
- múltiples providers
- memoria persistente
- uso local o en red

Si querés extenderlo, lo más natural es seguir mejorando:
- UX del chat
- providers adicionales
- manejo de cuotas/errores por proveedor
- cifrado local de credenciales
