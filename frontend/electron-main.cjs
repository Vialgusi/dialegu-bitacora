// Proceso principal de Dialegu Bitácora.
// Arranca el motor en un puerto libre con un token propio y expone el puente de preload.cjs.
// Contrato en docs/CONTRATO-MOTOR.md.

const { app, BrowserWindow, Menu, dialog, ipcMain, session, shell } = require('electron');
const crypto = require('crypto');
const fs = require('fs');
const net = require('net');
const path = require('path');
const { pathToFileURL } = require('url');
const { spawn } = require('child_process');

const NOMBRE_APP = 'Dialegu Bitácora';
const DATOS = path.join(process.env.LOCALAPPDATA || app.getPath('userData'), 'Dialegu Bitacora');
const EXTENSIONES_AUDIO = ['mp3', 'wav', 'm4a', 'aac', 'ogg', 'opus', 'flac', 'wma', 'webm', 'mp4', 'mov', 'mkv', 'avi'];

let ventana = null;
let motor = null; // { proceso, url, token, listo: Promise }

// --- Motor ---------------------------------------------------------------------

function puertoLibre() {
  return new Promise((resolver, rechazar) => {
    const servidor = net.createServer();
    servidor.unref();
    servidor.on('error', rechazar);
    servidor.listen(0, '127.0.0.1', () => {
      const { port } = servidor.address();
      servidor.close(() => resolver(port));
    });
  });
}

function comandoDelMotor(puerto, token) {
  const argumentos = ['--puerto', String(puerto), '--token', token, '--datos', DATOS, '--padre', String(process.pid)];
  if (app.isPackaged) {
    return { ejecutable: path.join(process.resourcesPath, 'Dialegu_Engine', 'Dialegu_Engine.exe'), argumentos, cwd: undefined };
  }
  const raiz = path.join(__dirname, '..');
  const python = process.env.BITACORA_PYTHON || path.join(raiz, 'venv', 'Scripts', 'python.exe');
  return { ejecutable: python, argumentos: ['-m', 'backend.servidor', ...argumentos], cwd: raiz };
}

async function esperarMotor(url, token, proceso) {
  for (let intento = 0; intento < 240; intento++) {
    if (proceso.exitCode !== null) throw new Error('El motor se cerró al iniciar. Revise motor.log en ' + DATOS);
    try {
      const respuesta = await fetch(`${url}/api/salud`, { headers: { 'X-Token': token } });
      if (respuesta.ok) return;
    } catch {
      // aún no escucha
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('El motor no respondió a tiempo.');
}

async function iniciarMotor() {
  fs.mkdirSync(DATOS, { recursive: true });
  const puerto = await puertoLibre();
  const token = crypto.randomBytes(32).toString('hex');
  const { ejecutable, argumentos, cwd } = comandoDelMotor(puerto, token);
  // Se conserva el registro de la sesión anterior para poder diagnosticar fallos tras reiniciar la app.
  const rutaRegistro = path.join(DATOS, 'motor.log');
  try { fs.renameSync(rutaRegistro, path.join(DATOS, 'motor.anterior.log')); } catch { /* primera vez */ }
  const registro = fs.createWriteStream(rutaRegistro, { flags: 'w' });
  const proceso = spawn(ejecutable, argumentos, { cwd, windowsHide: true, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
  proceso.stdout.pipe(registro);
  proceso.stderr.pipe(registro);
  proceso.on('error', (error) => registro.write(`No se pudo iniciar el motor: ${error.message}\n`));
  const url = `http://127.0.0.1:${puerto}`;
  motor = { proceso, url, token, listo: esperarMotor(url, token, proceso) };
  motor.listo.catch(() => {}); // el error se entrega cuando la interfaz pide motor()
}

function detenerMotor() {
  if (!motor || motor.proceso.exitCode !== null) return;
  if (process.platform === 'win32') {
    spawn('taskkill', ['/pid', String(motor.proceso.pid), '/f', '/t'], { windowsHide: true });
  } else {
    motor.proceso.kill('SIGTERM');
  }
}

// --- Archivos ------------------------------------------------------------------

function carpetaDocumentos(...partes) {
  const carpeta = path.join(app.getPath('documents'), NOMBRE_APP, ...partes);
  fs.mkdirSync(carpeta, { recursive: true });
  return carpeta;
}

function nombreSeguro(texto) {
  return (texto || 'sesion').replace(/[<>:"/\\|?*\u0000-\u001f]+/g, '').trim().slice(0, 80) || 'sesion';
}

function registrarPuente() {
  ipcMain.handle('motor', async () => {
    await motor.listo;
    return { url: motor.url, token: motor.token };
  });

  ipcMain.handle('elegir-audio', async () => {
    const { canceled, filePaths } = await dialog.showOpenDialog(ventana, {
      title: 'Cargar audio o video',
      properties: ['openFile'],
      filters: [{ name: 'Audio o video', extensions: EXTENSIONES_AUDIO }, { name: 'Todos los archivos', extensions: ['*'] }],
    });
    return canceled ? null : filePaths[0];
  });

  ipcMain.handle('guardar-archivo', async (_e, { nombreSugerido, datos, extension }) => {
    const { canceled, filePath } = await dialog.showSaveDialog(ventana, {
      title: 'Exportar',
      defaultPath: path.join(carpetaDocumentos(), `${nombreSeguro(nombreSugerido)}.${extension}`),
      filters: [{ name: extension.toUpperCase(), extensions: [extension] }],
    });
    if (canceled || !filePath) return null;
    await fs.promises.writeFile(filePath, Buffer.from(datos));
    return filePath;
  });

  ipcMain.handle('guardar-proyecto', async (_e, { transcripcion, rutaProyecto }) => {
    let ruta = rutaProyecto;
    if (!ruta) {
      const { canceled, filePath } = await dialog.showSaveDialog(ventana, {
        title: 'Guardar proyecto',
        defaultPath: path.join(carpetaDocumentos('Proyectos'), `${nombreSeguro(transcripcion?.meta?.nombre)}.bitacora`),
        filters: [{ name: 'Proyecto de Bitácora', extensions: ['bitacora'] }],
      });
      if (canceled || !filePath) return null;
      ruta = filePath;
    }
    await fs.promises.writeFile(ruta, JSON.stringify(transcripcion, null, 1), 'utf-8');
    return ruta;
  });

  ipcMain.handle('abrir-proyecto', async () => {
    const { canceled, filePaths } = await dialog.showOpenDialog(ventana, {
      title: 'Abrir proyecto',
      defaultPath: carpetaDocumentos('Proyectos'),
      properties: ['openFile'],
      filters: [{ name: 'Proyecto de Bitácora', extensions: ['bitacora'] }],
    });
    if (canceled) return null;
    const ruta = filePaths[0];
    const transcripcion = JSON.parse(await fs.promises.readFile(ruta, 'utf-8'));
    if (transcripcion?.version !== 1 || !Array.isArray(transcripcion.turnos)) {
      throw new Error('El archivo no es un proyecto válido de Dialegu Bitácora.');
    }
    const audio = transcripcion.meta?.audio_original;
    const urlAudio = audio && fs.existsSync(audio) ? pathToFileURL(audio).href : null;
    return { ruta, transcripcion, urlAudio };
  });

  ipcMain.handle('mostrar-en-carpeta', (_e, ruta) => {
    shell.showItemInFolder(ruta);
    return true;
  });
}

// --- Ventana -------------------------------------------------------------------

function proteger() {
  // Ningún permiso del navegador (micrófono, cámara, notificaciones…): la app solo carga archivos.
  session.defaultSession.setPermissionRequestHandler((_wc, _permiso, responder) => responder(false));
  if (app.isPackaged) {
    session.defaultSession.webRequest.onHeadersReceived((detalles, responder) => {
      responder({
        responseHeaders: {
          ...detalles.responseHeaders,
          'Content-Security-Policy': [
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; " +
              "connect-src http://127.0.0.1:*; media-src 'self' file: blob: http://127.0.0.1:*",
          ],
        },
      });
    });
  }
}

function crearVentana() {
  ventana = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 900,
    minHeight: 640,
    icon: path.join(__dirname, 'build', 'icon.ico'),
    autoHideMenuBar: true,
    title: NOMBRE_APP,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  const urlDesarrollo = process.env.VITE_DEV_SERVER_URL;
  if (urlDesarrollo) ventana.loadURL(urlDesarrollo);
  else ventana.loadFile(path.join(__dirname, 'dist', 'index.html'));

  // Enlaces externos al navegador; nunca dentro de la app.
  ventana.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) shell.openExternal(url);
    return { action: 'deny' };
  });
  ventana.webContents.on('will-navigate', (evento, url) => {
    if (url !== ventana.webContents.getURL()) evento.preventDefault();
  });
  ventana.on('closed', () => {
    ventana = null;
  });
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (ventana) {
      if (ventana.isMinimized()) ventana.restore();
      ventana.focus();
    }
  });

  app.whenReady().then(async () => {
    proteger();
    // Sin el menú por defecto: sus atajos (Ctrl+R recarga y pierde cambios, Ctrl+Q…) chocan con los de la revisión.
    Menu.setApplicationMenu(null);
    registrarPuente();
    await iniciarMotor();
    crearVentana();
  });

  app.on('window-all-closed', () => app.quit());
  app.on('will-quit', () => {
    detenerMotor();
  });
}
