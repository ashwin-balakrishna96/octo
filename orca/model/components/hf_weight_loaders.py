import functools as ft
import os.path as osp
import pickle as pkl

from flax.core import freeze, unfreeze
import jax.numpy as jnp
from transformers import AutoConfig, FlaxAutoModel, FlaxT5EncoderModel

import orca
from orca.model.components.clip import clip_weights_loader


def hf_weights_loader(params, hf_model):
    if "t5" in hf_model:
        config = AutoConfig.from_pretrained(hf_model)
        model = FlaxT5EncoderModel.from_pretrained(hf_model, config=config)
    else:
        model = FlaxAutoModel.from_pretrained(hf_model)

    model_def, model_variables = model.module, model.params
    replaced = False

    def find_and_replace(params, key, replacement):
        nonlocal replaced
        for k in params.keys():
            if k == key:
                params[k] = replacement
                print(f"Replaced {key} in params")
                replaced = True
                return
            if isinstance(params[k], type(params)):
                find_and_replace(params[k], key, replacement)

    params = params.unfreeze()
    find_and_replace(params, "hf_model", model_variables)
    assert replaced, "Failed to load weights"
    return freeze(params)


def resnet18_IN_SimCLR_loader(params, checkpoint=None):
    if checkpoint is None:
        base_folder = osp.dirname(orca.__file__)
        checkpoint = osp.join(base_folder, "../pretrained_weights/IN_1M_resnet18.pkl")
    with open(checkpoint, "rb") as f:
        checkpoint = pkl.load(f)

    replaced = False

    def replace_weights(param_dict, replacement_dict):
        nonlocal replaced
        for k in replacement_dict.keys():
            if k == "conv_init":
                old_shape = param_dict[k]["kernel"].shape

                base_conv = jnp.array(replacement_dict[k]["kernel"])
                num_tiles = int(old_shape[2] // base_conv.shape[2]) + 1
                num_extra = base_conv.shape[2] - old_shape[2] % base_conv.shape[2]
                new_param = jnp.tile(base_conv, (1, 1, num_tiles, 1))[
                    :, :, :-num_extra, :
                ]

                assert old_shape == new_param.shape, "shapes don't match!"
                param_dict[k]["kernel"] = new_param
                replaced = True
            elif isinstance(replacement_dict[k], dict):
                assert isinstance(param_dict[k], dict), "keys don't match!"
                replace_weights(param_dict[k], replacement_dict[k])
            else:
                assert (
                    param_dict[k].shape == replacement_dict[k].shape
                ), "shapes don't match!"
                param_dict[k] = jnp.array(replacement_dict[k])
                replaced = True

    params = unfreeze(params)
    replace_weights(
        params["orca_transformer"]["observation_tokenizers_0"]["ResNetEncoder_0"],
        checkpoint,
    )
    assert replaced, "Failed to load weights"
    print("loaded resnet18_IN_SimCLR")
    return freeze(params)


# index for weight loaders
# these are called to replace parameters after they are initialized from scratch
weights_loaders = {
    "clip": clip_weights_loader,
    "distilbert": ft.partial(hf_weights_loader, hf_model="distilbert-base-uncased"),
    "resnet18-IN-SimCLR": resnet18_IN_SimCLR_loader,
    "from_huggingface": hf_weights_loader,
}
