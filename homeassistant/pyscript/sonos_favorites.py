# /homeassistant/pyscript/sonos_favorites.py
from pprint import pformat

FAVMAP = {}  # title -> {"id": ..., "type": ...}
MASTER = "media_player.sonos_1"
SELECT = "input_select.sonos_1_favorite"

async def _browse(entity_id, media_content_id=None, media_content_type=None):
    """Call media_player.browse_media and return the BrowseMedia object."""
    kwargs = {"entity_id": entity_id}
    if media_content_id is not None:
        kwargs["media_content_id"] = media_content_id
    if media_content_type is not None:
        kwargs["media_content_type"] = media_content_type
    try:
        browse_result = await service.call("media_player", "browse_media", **kwargs)
        if browse_result:
            return browse_result.get(entity_id)
        return None
    except Exception as e:
        log.error(f"browse_media failed: {str(e)}")
        return None

async def _find_favorites_node(entity_id, node):
    """Find the specific 'Favorites' node to search within."""
    if not node:
        return None
    # --- FIX IS HERE ---
    # Search the children of the current node for one named "Favorites"
    for child in node.children or []:
        if child.title == "Favorites" and child.can_expand:
            log.info(f"Found 'Favorites' node. Browsing inside...")
            # Browse into the "Favorites" folder
            return await _browse(entity_id, child.media_content_id, child.media_content_type)
    return None
    # --- END FIX ---

async def _get_all_playable(entity_id, node):
    """Recursively get all playable items from a starting node."""
    items = []
    if not node:
        return items

    for child in node.children or []:
        if child.can_play:
            items.append((child.title, child.media_content_id, child.media_content_type))
        if child.can_expand:
            log.info(f"Expanding child folder: '{child.title}'")
            sub_node = await _browse(entity_id, child.media_content_id, child.media_content_type)
            items.extend(await _get_all_playable(entity_id, sub_node))
    return items

@service("pyscript.sonos_refresh_favorites_1")
async def sonos_refresh_favorites_1():
    """Populate input_select with items from 'Favorites'."""
    global FAVMAP
    log.info("sonos_refresh_favorites_1 service called. Starting targeted scan for 'Favorites'.")
    
    root_node = await _browse(MASTER)
    if not root_node:
        log.error("Failed to get a valid root node from browse_media. Aborting.")
        return
        
    # First, find the specific "Favorites" folder.
    favorites_root = await _find_favorites_node(MASTER, root_node)
    
    if not favorites_root:
        log.warning("Could not find an expandable 'Favorites' folder in the media browser.")
        options = ["('Favorites' not found)"]
        await service.call("input_select", "set_options", entity_id=SELECT, options=options)
        return

    # Now, get all playable items from *within* that folder.
    flat = await _get_all_playable(MASTER, favorites_root)
    
    log.info(f"Found {len(flat)} total playable items in 'Favorites': {flat}")

    seen = set()
    uniq = []
    for title, mcid, mctype in flat:
        if title not in seen:
            seen.add(title)
            uniq.append((title, mcid, mctype))

    options = ["(choose favorite)"] + [t for (t, _, _) in uniq] if uniq else ["(no favorites found)"]
    log.info(f"Final options to be set for input_select: {options}")
    await service.call("input_select", "set_options", entity_id=SELECT, options=options)
    FAVMAP = {t: {"id": mcid, "type": mctype} for (t, mcid, mctype) in uniq}
    log.info(f"Sonos 1 favorites refreshed: {len(uniq)} items")


@service("pyscript.sonos_play_selected_favorite_1")
async def sonos_play_selected_favorite_1(option: str = None):
    """Play the currently selected dropdown item on Sonos 1."""
    global FAVMAP
    if not option:
        option = state.get(SELECT)
    if not option or option.startswith("("):
        log.warning("No playable Sonos favorite selected")
        return
    if not FAVMAP:
        await sonos_refresh_favorites_1()
    item = FAVMAP.get(option)
    if not item:
        log.warning(f"No mapping found for '{option}' (try refreshing)")
        return
    await service.call(
        "media_player",
        "play_media",
        entity_id=MASTER,
        media_content_id=item["id"],
        media_content_type=item["type"],
    )

