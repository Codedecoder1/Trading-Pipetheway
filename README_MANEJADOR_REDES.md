# 📱 Guía Rápida para Manejador de Redes
## Fundación Verano Ardiente - Carrusel de Patrocinadores en Instagram

¡Hola! Esta es una guía simplificada para generar y publicar las imágenes de agradecimiento a patrocinadores en Instagram.

---

## 🚀 La Forma Más Fácil: Usar el Template HTML

### ✅ Método Recomendado (Sin necesidad de programación)

1. **Abre el archivo**: `sponsor_carousel_template.html`
   - Haz doble clic en el archivo
   - Se abrirá en tu navegador automáticamente

2. **Completa la información**:
   - Nombre de la Fundación
   - Eslogan/Tagline
   - Colores (puedes cambiarlos)
   - Logo de la fundación (si tienes)

3. **Agrega los patrocinadores**:
   - Nombre: ej. "Coca-Cola"
   - Logo: Selecciona la imagen (PNG, JPG, etc.)
   - Clic en "➕ Agregar Patrocinador"

4. **Ve la vista previa** (lado derecho):
   - Aparecerá en tiempo real
   - "📄 Portada" para ver la portada
   - "📊 Grilla 1" para ver patrocinadores

5. **Descarga las imágenes**:
   - Clic en "🚀 Generar Todas las Imágenes"
   - Se descargarán automáticamente a tu carpeta "Descargas"

---

## 📥 Después de Descargar

Las imágenes estarán en tu carpeta **Descargas** con nombres como:
- `fundacion_carousel_TIMESTAMP_1.png` (Portada)
- `fundacion_carousel_TIMESTAMP_2.png` (Patrocinadores)
- `fundacion_carousel_TIMESTAMP_3.png` (más patrocinadores, si hay)

---

## 📸 Subir a Instagram

### Paso 1: Abre Instagram
- Ve a instagram.com o abre la app
- Inicia sesión en la cuenta de la Fundación

### Paso 2: Crea un Carrusel
- Toca el botón **"+"** (crear post)
- Selecciona **"Carrusel"** (múltiples imágenes)

### Paso 3: Sube las Imágenes
- **Importante**: Selecciona EN ORDEN (primero la portada, luego las grillas)
- Puedes arrastrar las imágenes para reorganizar si es necesario

### Paso 4: Redacta el Caption

Copia y personaliza este texto:

```
Gracias 💚 a todos nuestros patrocinadores que hacen posible Verano Ardiente.

Sin su apoyo y confianza, nuestras iniciativas no serían posibles.

¡Nos alegra trabajar juntos por una causa común!

¿Tú también quieres apoyar? Contáctanos 📧

#VeranoArdiente #Patrocinadores #Agradecimiento #Fundación #Sostenibilidad
```

### Paso 5: Etiqueta a los Patrocinadores
- En los comentarios, menciona a las empresas: `@empresa1 @empresa2`
- O úsalas en el caption si Instagram lo permite

### Paso 6: Configura la Publicación
- **Quién puede comentar**: Todos (o solo seguidores)
- **Desactiva comentarios ofensivos** (opcional)
- **Agrupa comentarios** (para evitar spam)

### Paso 7: ¡Publica!
- Clic en **"Compartir"**
- Espera 10-15 segundos a que suba
- ¡Listo! 🎉

---

## 💡 Consejos Profesionales

### Mejor Momento para Publicar
- **Martes, miércoles o jueves**
- **Entre 11 AM - 2 PM** (hora local)
- Evita viernes noche (menos engagement)

### Después de Publicar
✅ **Day 1**: Responde los comentarios de patrocinadores
✅ **Day 2**: Comparte en tu Stories ("repost")
✅ **Day 3**: Pide a los patrocinadores que compartan

### Métricas a Revisar
- Alcance (cuántas personas lo ven)
- Guardados (importante para algoritmo)
- Clics en enlaces (si incluyes)
- Menciones de patrocinadores

---

## ❓ Preguntas Frecuentes

### P: ¿Qué pasa si tengo MÁS de 81 patrocinadores?
R: Crea 2 carruseles:
- Carrusel 1: Patrocinadores principales
- Carrusel 2: Patrocinadores adicionales
- Usa hashtags #parte1 #parte2

### P: ¿Los logos se ven pixelados?
R: Asegúrate que cada logo sea mínimo 300x300 píxeles en alta calidad

### P: ¿Puedo cambiar los colores?
R: Sí, en el template HTML hay un selector de color

### P: ¿Debo incluir el logo de la fundación?
R: Sí, recomendamos incluirlo para branding (en la portada)

### P: ¿Y si un patrocinador no me dio logo?
R: El sistema crea un rectángulo gris con el nombre (no se ve profesional, pide el logo)

### P: ¿Puedo usar el template en celular?
R: No, es mejor en computadora. Los archivos se descargan mejor.

---

## 🛠️ Alternativa: Si Prefieres Usar Python

Si alguien del equipo sabe programación, puede usar:

```bash
# 1. Editar sponsors_config.json con los patrocinadores
# 2. Poner logos en sponsors_logos/

# 3. Ejecutar:
python generate_sponsor_images.py

# Las imágenes se generarán en output/instagram_carousel/
```

---

## 📁 Archivos Disponibles

```
📦 Proyecto/
├── 📄 README_MANEJADOR_REDES.md (esta guía)
├── 📄 FUNDACION_GUIDE.md (guía detallada)
├── 🌐 sponsor_carousel_template.html ← USAR ESTE (fácil)
├── 🐍 generate_sponsor_images.py (alternativa Python)
├── ⚙️ sponsors_config.json (configuración)
├── 📁 sponsors_logos/ (coloca los logos aquí)
│   ├── empresa1.png
│   ├── empresa2.png
│   └── ...
└── 📁 output/
    └── instagram_carousel/ (aquí irán las imágenes generadas)
```

---

## ✅ Checklist Antes de Publicar

- [ ] ¿Todos los logos se ven claros?
- [ ] ¿La portada incluye el logo de la fundación?
- [ ] ¿Hay máximo 10 imágenes (formato Instagram)?
- [ ] ¿El texto contrasta bien con el fondo?
- [ ] ¿Revisaste en versión mobile?
- [ ] ¿Preparaste el caption con hashtags?
- [ ] ¿Confirmaste que subas en orden correcto?

---

## 🆘 Soporte / Problemas

Si algo no funciona:

1. **Cierra y abre nuevamente** el navegador
2. **Limpia el caché** del navegador (Ctrl+Shift+Del)
3. **Intenta otro navegador** (Chrome, Firefox, Safari)
4. **Verifica que los logos sean válidos** (PNG/JPG, no corrupto)
5. **Revisa el tamaño de archivos** (menores a 10MB cada uno)

---

## 📞 Contacto

¿Dudas? ¡Escríbeme! 

Estoy disponible para:
- Revisar las imágenes antes de publicar
- Ajustar diseños o colores
- Agregar más patrocinadores
- Rehacer el carrusel si es necesario

---

**¡Gracias por representar a Fundación Verano Ardiente!** 💚

*Última actualización: Septiembre 2026*
*Versión: 1.0*
