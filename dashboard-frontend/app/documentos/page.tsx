"use client";

import React, { useState, useRef } from "react";
import { UploadCloud, FileText, Download, Layers, Minimize } from "lucide-react";

export default function DocumentosPage() {
  const [activeTab, setActiveTab] = useState<"convert" | "bundle" | "compress">("convert");
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      setFiles(Array.from(e.dataTransfer.files));
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFiles(Array.from(e.target.files));
    }
  };

  const clearFiles = () => {
    setFiles([]);
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleProcess = async () => {
    if (files.length === 0) return;
    setLoading(true);
    setError(null);

    const formData = new FormData();
    files.forEach(file => formData.append("files", file));

    let endpoint = "";
    if (activeTab === "convert") endpoint = "/api/documentos/convert";
    else if (activeTab === "bundle") endpoint = "/api/documentos/bundle";
    else if (activeTab === "compress") endpoint = "/api/documentos/compress";

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Error procesando los archivos");
      }

      // Handle file download
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;

      const disposition = response.headers.get("Content-Disposition");
      let filename = "resultado";
      if (disposition && disposition.indexOf("filename=") !== -1) {
        const matches = /filename="([^"]*)"/.exec(disposition);
        if (matches != null && matches[1]) filename = matches[1];
      } else {
        if (activeTab === "convert" && files.length > 1) filename = "conversiones.zip";
        else filename = "resultado.pdf";
      }

      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err.message || "Error inesperado");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="mb-6">
        <h1 className="text-2xl font-black uppercase tracking-wider text-foreground/90">
          Herramientas de Documentos
        </h1>
        <p className="text-muted-foreground mt-1">
          Utilidades rápidas para procesar archivos sin necesidad de iniciar sesión.
        </p>
      </div>

      <div className="flex gap-4 mb-6">
        <button
          onClick={() => { setActiveTab("convert"); clearFiles(); }}
          className={`flex items-center gap-2 px-4 py-3 rounded border transition-colors ${
            activeTab === "convert"
              ? "bg-[rgba(108,77,255,0.15)] border-[rgba(108,77,255,0.4)] text-foreground"
              : "bg-[rgba(17,19,26,0.55)] border-border/70 text-muted-foreground hover:text-foreground"
          }`}
        >
          <FileText size={18} />
          <span className="font-semibold uppercase text-xs tracking-wider">Convertir a PDF</span>
        </button>
        <button
          onClick={() => { setActiveTab("bundle"); clearFiles(); }}
          className={`flex items-center gap-2 px-4 py-3 rounded border transition-colors ${
            activeTab === "bundle"
              ? "bg-[rgba(108,77,255,0.15)] border-[rgba(108,77,255,0.4)] text-foreground"
              : "bg-[rgba(17,19,26,0.55)] border-border/70 text-muted-foreground hover:text-foreground"
          }`}
        >
          <Layers size={18} />
          <span className="font-semibold uppercase text-xs tracking-wider">Fusionar PDFs</span>
        </button>
        <button
          onClick={() => { setActiveTab("compress"); clearFiles(); }}
          className={`flex items-center gap-2 px-4 py-3 rounded border transition-colors ${
            activeTab === "compress"
              ? "bg-[rgba(108,77,255,0.15)] border-[rgba(108,77,255,0.4)] text-foreground"
              : "bg-[rgba(17,19,26,0.55)] border-border/70 text-muted-foreground hover:text-foreground"
          }`}
        >
          <Minimize size={18} />
          <span className="font-semibold uppercase text-xs tracking-wider">Comprimir PDF</span>
        </button>
      </div>

      <div className="bg-[rgba(17,19,26,0.55)] border border-border/70 rounded p-6">
        <div className="mb-4">
          <h2 className="text-lg font-bold">
            {activeTab === "convert" && "Convertir imágenes a PDF"}
            {activeTab === "bundle" && "Unir varios PDFs en uno solo"}
            {activeTab === "compress" && "Comprimir archivo PDF"}
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            {activeTab === "convert" && "Sube varias imágenes (png, jpg, jpeg) y se devolverán en archivos PDF individuales (en un ZIP si son varias)."}
            {activeTab === "bundle" && "Sube 2 o más archivos PDF para unirlos en un único documento."}
            {activeTab === "compress" && "Sube un archivo PDF para reducir su tamaño."}
          </p>
        </div>

        <div
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          className="border-2 border-dashed border-border/70 hover:border-[rgba(108,77,255,0.5)] rounded-lg p-12 flex flex-col items-center justify-center transition-colors bg-background/30 cursor-pointer"
          onClick={() => fileInputRef.current?.click()}
        >
          <UploadCloud size={48} className="text-muted-foreground/60 mb-4" />
          <p className="text-center font-medium mb-1">
            Arrastra archivos aquí o haz clic para subir
          </p>
          <p className="text-xs text-muted-foreground text-center">
            {activeTab === "convert" && "Soporta JPG, PNG"}
            {(activeTab === "bundle" || activeTab === "compress") && "Soporta solo PDF"}
          </p>
          <input
            type="file"
            multiple={activeTab !== "compress"}
            accept={
              activeTab === "convert"
                ? "image/*"
                : ".pdf"
            }
            className="hidden"
            ref={fileInputRef}
            onChange={handleFileSelect}
          />
        </div>

        {files.length > 0 && (
          <div className="mt-6">
            <h3 className="text-sm font-semibold mb-2">Archivos seleccionados ({files.length}):</h3>
            <ul className="space-y-2 mb-4">
              {files.map((file, i) => (
                <li key={i} className="text-sm bg-background/50 px-3 py-2 rounded border border-border/50 flex justify-between items-center">
                  <span className="truncate max-w-[80%]">{file.name}</span>
                  <span className="text-xs text-muted-foreground">{(file.size / 1024 / 1024).toFixed(2)} MB</span>
                </li>
              ))}
            </ul>

            {error && (
              <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 text-red-500 rounded text-sm">
                {error}
              </div>
            )}

            <div className="flex gap-3">
              <button
                onClick={handleProcess}
                disabled={loading}
                className="flex items-center gap-2 bg-[rgba(108,77,255,0.8)] hover:bg-[rgba(108,77,255,1)] text-white px-5 py-2.5 rounded font-bold transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? (
                  <>Procesando...</>
                ) : (
                  <>
                    <Download size={18} />
                    {activeTab === "convert" && "Convertir a PDF"}
                    {activeTab === "bundle" && "Fusionar PDFs"}
                    {activeTab === "compress" && "Comprimir PDF"}
                  </>
                )}
              </button>
              <button
                onClick={clearFiles}
                disabled={loading}
                className="px-5 py-2.5 rounded border border-border/70 hover:bg-background/50 transition disabled:opacity-50 text-sm font-medium"
              >
                Limpiar
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
