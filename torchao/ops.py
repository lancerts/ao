import torch
from torch import Tensor
from torchao.quantization.utils import TORCH_VERSION_AFTER_2_4

def register_custom_op(name):
    def decorator(func):
        if TORCH_VERSION_AFTER_2_4:
            return torch.library.register_fake(f"{name}")(func)
        else:
            return torch.library.impl_abstract(f"{name}")(func)
    return decorator



def prepack_fp6_weight(fp6_weight: Tensor) -> Tensor:
    """
    Pack FP6 tensor in a layout for use with FP6-LLM. See https://arxiv.org/abs/2401.14112 for more details.

    Arguments
        fp6_weight: tightly-packed fp6_weight, inside a `torch.int32` container

    Returns
        packed FP6 tensor for use with FP6-LLM, inside a `torch.int32` container
    """
    return torch.ops.torchao.prepack_fp6_weight.default(fp6_weight)


# Defines the meta kernel / fake kernel / abstract impl
@register_custom_op("torchao::prepack_fp6_weight")
def _(fp6_weight):
    torch._check(fp6_weight.dim() == 2, lambda: f"weight should be a 2d tensor, got {fp6_weight.dim()}D")
    return torch.empty_like(fp6_weight)


def fp16_to_fp6(fp16_tensor: Tensor) -> Tensor:
    """
    Pack FP16 tensor (containing only FP6 values) into FP6 tensor.
    """
    return torch.ops.torchao.fp16_to_fp6.default(fp16_tensor)


@register_custom_op("torchao::fp16_to_fp6")
def _(fp16_tensor):
    torch._check(fp16_tensor.dim() == 2, lambda: f"weight should be a 2d tensor, got {fp16_tensor.dim()}D")
    torch._check(fp16_tensor.dtype is torch.float16, lambda: f"weight must be FP16, got {fp16_tensor.dtype}")
    M, K = fp16_tensor.shape
    torch._check(K % 4  == 0, lambda: f"second dimension must be a multiple of 4, got {K}")
    return torch.empty((M, K * 6 // 8), dtype=torch.uint8, device=fp16_tensor.device)


def fp16act_fp6weight_linear(_in_feats: Tensor, _weights: Tensor, _scales: Tensor, splitK: int = 1) -> Tensor:
    """
    FP6-LLM linear layer A @ W.T. See https://arxiv.org/abs/2401.14112 for more details.

    Arguments
        _in_feats: input activations in FP16
        _weights: packed FP6 weights. See :func:prepack_fp6_weight and :func:fp16_to_fp6
        _scales: scale
        splitK: split K

    Returns
        output of linear layer
    """
    return torch.ops.torchao.fp16act_fp6weight_linear.default(_in_feats, _weights, _scales, splitK)


@register_custom_op("torchao::fp16act_fp6weight_linear")
def _(_in_feats, _weights, _scales, splitK = 1):
    torch._check(_in_feats.dim() == 2, lambda: f"input should be a 2d tensor, got {_in_feats.dim()}D")
    torch._check(_in_feats.dtype is torch.float16, lambda: f"weight must be FP16, got {_in_feats.dtype}")
    torch._check(_weights.dim() == 2, lambda: f"weight should be a 2d tensor, got {_weights.dim()}D")
    torch._check(_weights.dtype is torch.int32, lambda: f"weight must be INT32, got {_weights.dtype}")
    torch._check(_scales.dim() == 1, lambda: f"scale should be a 2d tensor, got {_scales.dim()}D")
    torch._check(_scales.dtype is torch.float16, lambda: f"scale must be FP16, got {_scales.dtype}")

    BS, IC = _in_feats.shape
    OC, _ = _weights.shape
    torch._check(IC / 16 * 3 == _weights.shape[1], lambda: "Dimensions mismatched")
    torch._check(OC == _scales.shape[0], lambda: "Dimensions mismatched")

    return _in_feats.new_empty((BS, OC))


def fp6_weight_dequant(fp6_tensor: Tensor, fp16_scale: Tensor) -> Tensor:
    return torch.ops.torchao.fp6_weight_dequant.default(fp6_tensor, fp16_scale)


@register_custom_op("torchao::fp6_weight_dequant")
def _(fp6_tensor, fp16_scale):
    torch._check(fp6_tensor.dim() == 2, lambda: f"weight should be a 2d tensor, got {fp6_tensor.dim()}D")
    torch._check(fp6_tensor.dtype is torch.int32, lambda: f"weight must be INT32, got {fp6_tensor.dtype}")
    torch._check(fp16_scale.dim() == 1, lambda: f"scale should be a 2d tensor, got {fp16_scale.dim()}D")
    torch._check(fp16_scale.dtype is torch.float16, lambda: f"scale must be FP16, got {fp16_scale.dtype}")

    OC, _IC = fp6_tensor.shape
    torch._check(OC == fp16_scale.shape[0], lambda: "Dimensions mismatched")

    return fp16_scale.new_empty((OC, _IC * 16 // 3))
