#!/usr/bin/env python3
"""
Generador de Imágenes de Carrusel de Patrocinadores
Fundación Verano Ardiente

Este script genera automáticamente imágenes optimizadas para Instagram
con logos de patrocinadores organizados en grillas de 3x3.
"""

import json
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math


class SponsorCarouselGenerator:
    def __init__(self, config_path="sponsors_config.json"):
        self.config_path = config_path
        self.config = self._load_config()
        self.foundation_name = self.config['foundation']['name']
        self.sponsors = self.config['sponsors']
        self.output_dir = self.config['output']['directory']
        self._setup_output_dir()

    def _load_config(self):
        """Carga la configuración desde JSON."""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _setup_output_dir(self):
        """Crea la carpeta de salida si no existe."""
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        print(f"✓ Directorio de salida: {self.output_dir}")

    def _load_image_safe(self, image_path, size=(250, 250)):
        """Carga una imagen y la redimensiona de forma segura."""
        try:
            img = Image.open(image_path).convert('RGBA')
            # Redimensionar manteniendo proporción
            img.thumbnail(size, Image.Resampling.LANCZOS)
            # Crear fondo transparente
            background = Image.new('RGBA', size, (255, 255, 255, 0))
            # Centrar imagen en el fondo
            offset = ((size[0] - img.width) // 2, (size[1] - img.height) // 2)
            background.paste(img, offset, img)
            return background
        except Exception as e:
            print(f"⚠ Error cargando {image_path}: {e}")
            return None

    def _create_cover_image(self):
        """Crea la imagen de portada."""
        width = self.config['carousel_settings']['image_width']
        height = self.config['carousel_settings']['image_height']

        # Crear imagen con fondo blanco
        img = Image.new('RGB', (width, height),
                       color=self.config['foundation']['colors']['background'])
        draw = ImageDraw.Draw(img)

        # Intentar cargar logo de la fundación
        foundation_logo = None
        if os.path.exists(self.config['foundation']['logo_path']):
            foundation_logo = self._load_image_safe(
                self.config['foundation']['logo_path'],
                size=(400, 400)
            )

        # Dibujar logo de fundación
        if foundation_logo:
            offset = ((width - foundation_logo.width) // 2,
                     (height // 4 - foundation_logo.height // 2))
            img.paste(foundation_logo, offset, foundation_logo)

        # Dibujar textos
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
            subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
        except:
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()

        # Título
        title = "GRACIAS A NUESTROS"
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = (width - title_width) // 2
        draw.text((title_x, height // 2), title,
                 fill=self.config['foundation']['colors']['text'],
                 font=title_font)

        # Subtítulo
        subtitle = "PATROCINADORES"
        subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
        subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
        subtitle_x = (width - subtitle_width) // 2
        draw.text((subtitle_x, height // 2 + 100), subtitle,
                 fill=self.config['foundation']['colors']['primary'],
                 font=subtitle_font)

        # Pie de página
        footer = self.foundation_name
        try:
            footer_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
        except:
            footer_font = ImageFont.load_default()

        footer_bbox = draw.textbbox((0, 0), footer, font=footer_font)
        footer_width = footer_bbox[2] - footer_bbox[0]
        footer_x = (width - footer_width) // 2
        draw.text((footer_x, height - 80), footer,
                 fill=self.config['foundation']['colors']['text'],
                 font=footer_font)

        return img

    def _create_sponsor_grid_image(self, sponsors_chunk):
        """Crea una imagen con una grilla de sponsors."""
        width = self.config['carousel_settings']['image_width']
        height = self.config['carousel_settings']['image_height']

        img = Image.new('RGB', (width, height),
                       color=self.config['foundation']['colors']['background'])

        # Configuración de grilla
        grid_cols = 3
        grid_rows = 3
        sponsor_size = 250
        padding = 15

        # Cargar logos
        logos = []
        for sponsor in sponsors_chunk:
            logo_path = sponsor.get('logo_path')
            if logo_path and os.path.exists(logo_path):
                logo = self._load_image_safe(logo_path, size=(sponsor_size, sponsor_size))
                if logo:
                    logos.append(logo)
            else:
                # Crear placeholder
                placeholder = Image.new('RGB', (sponsor_size, sponsor_size),
                                       color=(200, 200, 200))
                draw = ImageDraw.Draw(placeholder)
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
                except:
                    font = ImageFont.load_default()
                text = sponsor.get('name', 'Sin logo')[:15]
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                x = (sponsor_size - text_width) // 2
                draw.text((x, sponsor_size // 2), text, fill=(100, 100, 100), font=font)
                logos.append(placeholder)

        # Posicionar logos en grilla
        start_y = 50
        col_width = (width - 2 * padding) // grid_cols

        for idx, logo in enumerate(logos[:9]):  # Máximo 9 sponsors por imagen
            row = idx // grid_cols
            col = idx % grid_cols

            x = padding + col * col_width + (col_width - sponsor_size) // 2
            y = start_y + row * (sponsor_size + padding)

            img.paste(logo, (x, y), logo)

        # Agregar texto de agradecimiento al pie
        draw = ImageDraw.Draw(img)
        try:
            footer_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        except:
            footer_font = ImageFont.load_default()

        footer_text = "GRACIAS A NUESTROS PATROCINADORES"
        footer_bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        footer_width = footer_bbox[2] - footer_bbox[0]
        footer_x = (width - footer_width) // 2
        draw.text((footer_x, height - 50), footer_text,
                 fill=self.config['foundation']['colors']['primary'],
                 font=footer_font)

        return img

    def generate(self):
        """Genera todas las imágenes del carrusel."""
        print("\n🎨 Iniciando generación de imágenes...\n")

        # Crear portada
        print("  📄 Generando portada...")
        cover_img = self._create_cover_image()
        cover_path = os.path.join(
            self.output_dir,
            f"{self.config['output']['filename_prefix']}_01.png"
        )
        cover_img.save(cover_path, 'PNG', quality=95, dpi=(300, 300))
        print(f"  ✓ Portada guardada: {cover_path}")

        # Dividir sponsors en chunks de 9
        sponsors_per_image = 9
        num_chunks = math.ceil(len(self.sponsors) / sponsors_per_image)

        print(f"\n  📸 Generando {num_chunks} imagen(es) con grillas de patrocinadores...")
        for chunk_idx, i in enumerate(range(0, len(self.sponsors), sponsors_per_image)):
            chunk = self.sponsors[i:i + sponsors_per_image]
            image_num = chunk_idx + 2  # Comenzar en 02 (01 es la portada)

            print(f"    • Imagen {image_num}: {len(chunk)} patrocinador(es)")
            grid_img = self._create_sponsor_grid_image(chunk)

            output_path = os.path.join(
                self.output_dir,
                f"{self.config['output']['filename_prefix']}_{image_num:02d}.png"
            )
            grid_img.save(output_path, 'PNG', quality=95, dpi=(300, 300))
            print(f"      ✓ Guardada: {output_path}")

        print("\n" + "="*60)
        print("✅ ¡Proceso completado exitosamente!")
        print("="*60)
        print(f"\n📁 Imágenes guardadas en: {os.path.abspath(self.output_dir)}")
        print(f"\n📊 Resumen:")
        print(f"   • Portada: 1 imagen")
        print(f"   • Grillas de patrocinadores: {num_chunks} imagen(es)")
        print(f"   • Total patrocinadores: {len(self.sponsors)}")
        print(f"   • Total imágenes generadas: {num_chunks + 1}")
        print(f"\n💡 Próximos pasos:")
        print(f"   1. Revisa las imágenes en {self.output_dir}")
        print(f"   2. Sube las imágenes a Instagram en orden (01, 02, 03...)")
        print(f"   3. Redacta el caption con agradecimientos")
        print(f"   4. ¡Publica! 🚀")


def main():
    try:
        generator = SponsorCarouselGenerator()
        generator.generate()
    except FileNotFoundError as e:
        print(f"❌ Error: No se encontró {e}")
        print("   Asegúrate de que sponsors_config.json existe")
    except json.JSONDecodeError as e:
        print(f"❌ Error en JSON: {e}")
        print("   Verifica que sponsors_config.json tenga formato válido")
    except Exception as e:
        print(f"❌ Error inesperado: {e}")


if __name__ == "__main__":
    main()
