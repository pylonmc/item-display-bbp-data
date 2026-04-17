from pathlib import Path
import shutil
import requests
import sys
import json

data_dir = Path("data")
shutil.rmtree(data_dir, ignore_errors=True)
data_dir.mkdir()

versions = requests.get("https://launchermeta.mojang.com/mc/game/version_manifest.json").json()["versions"]
version = sys.argv[1]

for v in versions:
    if v["id"] == version:
        version_url = v["url"]
        break
else:
    print(f"Version {version} not found.")
    sys.exit(1)

client_jar = data_dir / "client.zip"
version_data = requests.get(version_url).json()
client_url = version_data["downloads"]["client"]["url"]
with requests.get(client_url, stream=True) as response:
    response.raise_for_status()
    with open(client_jar, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

shutil.unpack_archive(client_jar, data_dir / "client")
client_jar.unlink()

assets_dir = data_dir / "client" / "assets" / "minecraft"
valid_item_models = {}
for item_file in (assets_dir / "items").glob("*.json"):
    model_info = json.loads(item_file.read_text())["model"]
    if model_info["type"] == "minecraft:model":
        model = model_info["model"]
        if model.startswith("minecraft:block/"):
            model = model[len("minecraft:block/"):]
            valid_item_models[item_file.stem] = model

models_dir = data_dir / "models"
models_dir.mkdir()

textures_dir = data_dir / "textures"
textures_dir.mkdir()

block_models_assets_dir = assets_dir / "models" / "block"

def merge_maps(map1, map2):
    result = map1.copy()
    for key, value in map2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_maps(result[key], value)
        else:
            result[key] = value
    return result

def flatten_parents(model_data: dict, stop_at: str | None = None):
    if "parent" in model_data:
        parent: str = model_data["parent"]
        if parent != stop_at:
            parent = parent.removeprefix("minecraft:")
            if not parent.startswith("block/"):
                raise ValueError(f"Unsupported parent model: {parent}")
            parent = parent[len("block/"):]
            parent_file = block_models_assets_dir / f"{parent}.json"
            parent_data = flatten_parents(json.loads(parent_file.read_text()), stop_at=stop_at)
            return merge_maps(parent_data, { key: value for key, value in model_data.items() if key != "parent" })
    return model_data

def resolve_textures(model_data: dict):
    textures: dict[str, str] = model_data["textures"]
    final = {}
    for element in model_data["elements"]:
        for face, spec in element["faces"].items():
            texture = spec["texture"]
            while texture.startswith("#"):
                texture = textures[texture[1:]]

            texture = texture.removeprefix("minecraft:")
            if not texture.startswith("block/"):
                raise ValueError(f"Unsupported texture: {texture}")
            texture = texture[len("block/"):]
            final[face] = texture

            texture_file = assets_dir / "textures" / "block" / f"{texture}.png"
            if not texture_file.exists():
                raise ValueError(f"Texture file not found: {texture_file}")
            texture_dest = textures_dir / f"{texture}.png"
            if not texture_dest.exists():
                shutil.copy(texture_file, texture_dest)
    return final

invalid_items = []
for item, model in valid_item_models.items():
    try:
        model_file = block_models_assets_dir / f"{model}.json"
        model_data = json.loads(model_file.read_text())
        model_data = flatten_parents(model_data, stop_at="block/cube")
        if "parent" in model_data and model_data["parent"] == "block/cube":
            model_data = flatten_parents(model_data)
            textures = resolve_textures(model_data)
            with open(models_dir / f"{model}.json", "w") as f:
                json.dump(textures, f)
        else:
            invalid_items.append(item)
    except Exception as e:
        raise e
        print(f"Error processing model {model}: {e}")

shutil.rmtree(data_dir / "client")

valid_item_models = { item: model for item, model in valid_item_models.items() if item not in invalid_items }
with open(data_dir / "items.json", "w") as f:
    json.dump(valid_item_models, f)
