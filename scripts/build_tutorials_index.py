import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import tutorials


def main():
    parser = argparse.ArgumentParser(
        description="Pre-indexa los tutoriales de docs/tutoriales con embeddings de OpenAI."
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("OPENAI_API_KEY", ""),
        help="Clave de API de OpenAI (default: env OPENAI_API_KEY).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reconstruir el índice completo aunque ya exista.",
    )
    args = parser.parse_args()

    api_key = (args.api_key or "").strip()
    if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
        print("⚠️ No hay OPENAI_API_KEY. Se generará el índice SIN embeddings (búsqueda por palabras clave).")
        print("   Para búsqueda semántica, provee --api-key o configura OPENAI_API_KEY.")

    if args.force and os.path.exists(tutorials.INDEX_PATH):
        os.remove(tutorials.INDEX_PATH)

    tutorials._instance = None
    index = tutorials.TutorialIndex.load(api_key=api_key or None)

    n_chunks = len(index.chunks)
    n_embedded = sum(1 for c in index.chunks if "embedding" in c)
    print(f"Índice listo: {n_chunks} secciones, {n_embedded} con embedding.")
    print(f"Guardado en: {tutorials.INDEX_PATH}")


if __name__ == "__main__":
    main()
