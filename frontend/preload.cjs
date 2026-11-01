// Puente entre la interfaz y Electron. Contrato en docs/CONTRATO-MOTOR.md §4.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('bitacora', {
  motor: () => ipcRenderer.invoke('motor'),
  elegirAudio: () => ipcRenderer.invoke('elegir-audio'),
  guardarArchivo: (opciones) => ipcRenderer.invoke('guardar-archivo', opciones),
  guardarProyecto: (opciones) => ipcRenderer.invoke('guardar-proyecto', opciones),
  abrirProyecto: () => ipcRenderer.invoke('abrir-proyecto'),
  mostrarEnCarpeta: (ruta) => ipcRenderer.invoke('mostrar-en-carpeta', ruta),
});
