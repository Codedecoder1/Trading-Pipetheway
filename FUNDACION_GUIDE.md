# 📸 Guía: Imágenes de Agradecimiento a Patrocinadores - Fundación Verano Ardiente

## Descripción General
Esta guía explica cómo generar imágenes de Instagram para agradecer a todos los patrocinadores de la Fundación Verano Ardiente. Las imágenes se organizan en carruseles de 9 patrocinadores por imagen (compatible con formato de 10 imágenes o 20 imágenes en Instagram).

---

## 📋 Estructura del Carrusel

- **Imagen 1**: Portada + Logo de la Fundación
- **Imágenes 2-10**: Grillas de 9 patrocinadores c/u
- **Patrón**: 9 logos por imagen (3x3)
- **Total**: Hasta 81 patrocinadores en un carrusel de 10 imágenes

---

## ✅ Pasos para Generar las Imágenes

### Paso 1: Recopilar Información de Patrocinadores

1. Obtén los **logos en formato PNG o JPG** de cada patrocinador
2. Crea una carpeta llamada `sponsors_logos/` en este proyecto
3. Nombra cada logo así: `01_empresa.png`, `02_empresa.png`, etc.
4. Organiza por orden de preferencia o importancia

### Paso 2: Configurar los Patrocinadores

Edita el archivo `sponsors_config.json`:

```json
{
  "sponsors": [
    {
      "id": 1,
      "name": "Empresa A",
      "logo": "sponsors_logos/01_empresa_a.png"
    },
    {
      "id": 2,
      "name": "Empresa B",
      "logo": "sponsors_logos/02_empresa_b.png"
    }
  ],
  "foundation": {
    "name": "Fundación Verano Ardiente",
    "logo": "foundation_logo.png",
    "tagline": "Gracias a nuestros patrocinadores"
  }
}
```

### Paso 3: Generar las Imágenes

**Opción A: Usando Python (Recomendado)**

```bash
python generate_sponsor_images.py
```

**Opción B: Usando Template Editable**

Abre `sponsor_carousel_template.html` en tu navegador y:
1. Sube los logos de patrocinadores
2. Configura colores y estilos
3. Descarga las imágenes generadas

### Paso 4: Validar las Imágenes

Revisa la carpeta `output/instagram_carousel/`:
- ✅ Debe haber 10 (o menos) imágenes PNG
- ✅ Cada imagen debe ser 1080x1350px (formato cuadrado optimizado)
- ✅ Resolución mínima 150 DPI
- ✅ Nombres: `fundacion_carousel_01.png`, `fundacion_carousel_02.png`, etc.

### Paso 5: Subir a Instagram

1. Ve a Instagram (app o web)
2. Crea un nuevo post (+ botón)
3. Selecciona **"Carrusel"**
4. Sube las imágenes en orden (01, 02, 03...)
5. **Importante**: Las imágenes se mostrarán en el orden que las subas
6. Redacta el caption:

```
Gracias 💚 a todos nuestros patrocinadores que hacen posible Verano Ardiente.

Sin su apoyo, nuestras iniciativas no serían posibles.

¿Tú también quieres apoyarnos? Contáctanos 📧

#VeranoArdiente #PatrocinadorEmpresa #Agradecimiento #Fundación
```

7. Configura:
   - Quién puede comentar: Todos
   - Tags: Etiqueta a los patrocinadores
   - Ubicación: Fundación Verano Ardiente (si existe)
8. Publica ✨

---

## 🎨 Especificaciones Técnicas

### Tamaño de Imagen
- **Ancho**: 1080 px
- **Alto**: 1350 px
- **Formato**: PNG (transparencia) o JPG
- **Proporción**: 4:5 (vertical, optimizado para Instagram)

### Colores Recomendados
- **Fondo**: Blanco (#FFFFFF) o degradado
- **Texto**: Negro (#000000) o con contraste
- **Acentos**: Colores de la fundación

### Textos en Imagen
```
Portada (Imagen 1):
┌─────────────────────────┐
│   [Logo Fundación]      │
│                         │
│  Gracias a nuestros     │
│  PATROCINADORES         │
│                         │
│  Verano Ardiente        │
└─────────────────────────┘

Grilla de Patrocinadores (Imágenes 2-10):
┌─────────────────────────┐
│ [Logo] [Logo] [Logo]    │
│ [Logo] [Logo] [Logo]    │
│ [Logo] [Logo] [Logo]    │
│                         │
│ "GRACIAS A NUESTROS     │
│  PATROCINADORES"        │
└─────────────────────────┘
```

---

## 📱 Consejos para Instagram

### Antes de Publicar
✅ Prueba el carrusel en el navegador de Instagram (usa Vista Previa)
✅ Verifica que los logos se vean claros y legibles
✅ Asegúrate de que los colores contrasten bien
✅ Prueba en modo celular

### Después de Publicar
✅ Responde comentarios de patrocinadores
✅ Etiqueta a las empresas patrocinadoras en los comentarios
✅ Comparte en tu Stories
✅ Pide a los patrocinadores que compartan la publicación

### Calendario Sugerido
- Martes o miércoles: Mejor engagement
- Entre 11:00 AM - 2:00 PM hora local
- Evita viernes noche (menor alcance)

---

## 🛠️ Archivos del Proyecto

```
proyecto/
├── FUNDACION_GUIDE.md                (esta guía)
├── sponsors_config.json              (configuración)
├── generate_sponsor_images.py         (script generador)
├── sponsor_carousel_template.html     (editor visual)
├── foundation_logo.png               (logo de fundación)
├── sponsors_logos/                   (carpeta con logos)
│   ├── 01_empresa_a.png
│   ├── 02_empresa_b.png
│   └── ... (más logos)
└── output/
    └── instagram_carousel/           (imágenes generadas)
        ├── fundacion_carousel_01.png
        ├── fundacion_carousel_02.png
        └── ... (más imágenes)
```

---

## 🔧 Solución de Problemas

### Problema: Las imágenes se ven pixeladas
**Solución**: Aumenta la resolución de los logos de entrada a mínimo 300px x 300px cada uno

### Problema: Los logos no caben bien
**Solución**: Redimensiona los logos a un tamaño uniforme (ej: 250x250px)

### Problema: Instagram dice que la imagen es muy pequeña
**Solución**: Verifica que sea exactamente 1080x1350px; Instagram rechaza imágenes menores a 600x600px

### Problema: Los colores se ven diferentes en Instagram
**Solución**: 
- Sube como PNG si es posible (mejor compresión)
- Evita fondos con patrones complejos
- Usa colores sólidos para mejor compatibilidad

### Problema: ¿Cómo hago si tengo más de 81 patrocinadores?
**Solución**: Crea dos carruseles:
- Carrusel 1: Patrocinadores principales (9)
- Carrusel 2: Patrocinadores adicionales
- Usa hashtags #patrocinadores #parte1 y #parte2

---

## 📞 Contacto y Soporte

Si tienes problemas con los pasos anteriores:
1. Verifica que los archivos estén en la carpeta correcta
2. Revisa que los logos sean PNG/JPG válidos
3. Comprueba que `sponsors_config.json` tenga formato JSON correcto
4. Ejecuta nuevamente el script generador

---

## 📝 Checklist Final

Antes de publicar en Instagram:

- [ ] Todas las imágenes están en `output/instagram_carousel/`
- [ ] Hay 1 portada + N imágenes de patrocinadores (mín 9, máx 10)
- [ ] Cada imagen es 1080x1350px
- [ ] Los logos se ven claros y legibles
- [ ] El texto contrasta bien con el fondo
- [ ] Caption está redactado y listo
- [ ] Hashtags relevantes están listos
- [ ] Etiquetas de patrocinadores confirmadas

¡**Listo para publicar!** 🎉

---

**Versión**: 1.0  
**Última actualización**: Septiembre 2026  
**Fundación**: Verano Ardiente
