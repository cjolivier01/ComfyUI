import comfy.model_management
import comfy.memory_management
import logging
import torch

try:
    import comfy_aimdo.host_buffer as aimdo_host_buffer
except Exception:
    aimdo_host_buffer = None

try:
    import comfy_aimdo.torch as aimdo_torch
except Exception:
    aimdo_torch = None

_WARNED_FALLBACK = False

from comfy.cli_args import args

def get_pin(module):
    return getattr(module, "_pin", None)

def pin_memory(module):
    global _WARNED_FALLBACK
    if module.pin_failed or args.disable_pinned_memory or get_pin(module) is not None:
        return
    #FIXME: This is a RAM cache trigger event
    size = comfy.memory_management.vram_aligned_size([ module.weight, module.bias ])

    if comfy.model_management.MAX_PINNED_MEMORY <= 0 or (comfy.model_management.TOTAL_PINNED_MEMORY + size) > comfy.model_management.MAX_PINNED_MEMORY:
        module.pin_failed = True
        return False

    try:
        if aimdo_host_buffer is not None and aimdo_torch is not None and hasattr(aimdo_torch, "hostbuf_to_tensor"):
            hostbuf = aimdo_host_buffer.HostBuffer(size)
            module._pin = aimdo_torch.hostbuf_to_tensor(hostbuf)
            module._pin_hostbuf = hostbuf
        else:
            if not _WARNED_FALLBACK:
                logging.warning("comfy_aimdo.host_buffer unavailable; using torch pinned-memory fallback.")
                _WARNED_FALLBACK = True
            module._pin = torch.empty(size, dtype=torch.uint8, pin_memory=True)
            module._pin_hostbuf = None
    except RuntimeError:
        module.pin_failed = True
        return False

    comfy.model_management.TOTAL_PINNED_MEMORY += size
    return True

def unpin_memory(module):
    if get_pin(module) is None:
        return 0
    size = module._pin.numel() * module._pin.element_size()

    comfy.model_management.TOTAL_PINNED_MEMORY -= size
    if comfy.model_management.TOTAL_PINNED_MEMORY < 0:
        comfy.model_management.TOTAL_PINNED_MEMORY = 0

    del module._pin
    if hasattr(module, "_pin_hostbuf"):
        del module._pin_hostbuf
    return size
