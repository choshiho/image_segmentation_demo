
#################################################
### THIS FILE WAS AUTOGENERATED! DO NOT EDIT! ###
#################################################
# file to edit: dev_nb/resnet_unet.ipynb

#================================================
import torchvision


#================================================
from torch import nn


#================================================
from torch.nn import functional as F


#================================================
import torch


#================================================
class Conv_Bn_ReLu(nn.Module):
    """
    Helper module that consists of a Conv -> BN -> ReLU
    """

    def __init__(self, chin, chout, kernel_size=3, padding=1, stride=1, with_nonlinearity=True):
        super().__init__()
        self.conv = nn.Conv2d(chin, chout, padding=padding, kernel_size=kernel_size, stride=stride)
        self.bn = nn.BatchNorm2d(chout)
        self.with_nonlinearity = with_nonlinearity

    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        if self.with_nonlinearity:
            x = F.relu(x)
        return x



#================================================
class Bridge(nn.Module):
    """
    The part connect Encoder and Decoder
    """

    def __init__(self, ch, with_shortcut):
        super().__init__()
        self.with_shortcut = with_shortcut
        self.conv1 = Conv_Bn_ReLu(ch,ch)
        if with_shortcut:
            self.conv2 = Conv_Bn_ReLu(ch,ch,with_nonlinearity=False)
        else:
            self.conv2 = Conv_Bn_ReLu(ch,ch)

        self.initialize_BnPreAdd()


    def initialize_BnPreAdd(self):
        """
        如果有残差连接，则把与残差连接相加处初始化为0
        """
        if self.with_shortcut:
            nn.init.zeros_(self.conv2.bn.weight)

    def forward(self, x):
        out = self.conv1(x)
        out = self.conv2(x)

        if self.with_shortcut:
            out += x
            out = F.relu(out)
        return out


#================================================
class UpBlock(nn.Module):
    """
    Up block that encapsulates one up-sampling step which consists of Upsample -> ConvBlock -> ConvBlock
    """

    def __init__(self, chin, chout, sideconnect='add', chside=None, upsample_method="conv_transpose"):
        """
        chin: input channel
        chout: output channel
        sideconnect: add/cat
        chside: channel of side-connect feature
        """
        super().__init__()
        self.sideconnect=sideconnect
        self.upsample_method = upsample_method

        if upsample_method == "conv_transpose":
            self.upsample = nn.Sequential(
                nn.ConvTranspose2d(chin, chout, kernel_size=2, stride=2, bias=False),
                nn.BatchNorm2d(chout)
            )
        elif upsampling_method == "bilinear":
            self.upsample = nn.Sequential(
                nn.Upsample(mode='bilinear', scale_factor=2),
                Conv_Bn_ReLu(chin,chout,1,padding=0,with_nonlinearity=False)
            )
        if sideconnect=='add':
            chmid = chout;
        elif sideconnect=='cat':
            chmid = chout + chside;
        self.conv1 = Conv_Bn_ReLu(chmid, chout)
        self.conv2 = Conv_Bn_ReLu(chout, chout)

        if sideconnect=='add':
            self.initialize_BnPreAdd()


    def initialize_BnPreAdd(self):
        """
        如果侧向连接方式为add，则把与侧向连接相加处初始化为0
        """
        if self.upsample_method == "conv_transpose":
            nn.init.zeros_(self.upsample[1].weight)
        elif self.upsampling_method == "bilinear":
            nn.init.zeros_(self.upsample[1].bn.weight)


    def forward(self, upx, sidex):
        """
        :param upx: this is the output from the previous up block
        :param sidex: this is the output from the down block
        :return: upsampled feature map
        """
        x = self.upsample(upx)
        if self.sideconnect=='add':
            x = x + sidex;
        elif self.sideconnect=='cat':
            x = torch.cat([x,sidex], 1)
        x = self.conv1(x)
        x = self.conv2(x)
        return x


#================================================
class Resnet_UNet(nn.Module):
    """
    以resnet为encoder的unet网络。而且在侧向连接中都使用了与resnet相似的方式，也可以选择用原unet的方式。
    """
    def __init__(self,
                 resnet=torchvision.models.resnet.resnet50(pretrained=True),
                 dwpath_chs = [3,   64,  256, 512, 1024, 2048],
                 uppath_chs = [128, 128, 256, 512, 1024, 2048],
                 bridge_shortcut = False,
                 side_connect = 'cat',
                 upsample_method = "conv_transpose",
                 n_classes=2):
        super().__init__()

        down_blocks = []
        down_blocks.append(nn.Sequential(resnet.conv1, resnet.bn1, resnet.relu))
        down_blocks.append(nn.Sequential(resnet.maxpool, resnet.layer1))
        down_blocks.append(resnet.layer2)
        down_blocks.append(resnet.layer3)
        down_blocks.append(resnet.layer4)
        self.down_blocks = nn.ModuleList(down_blocks)

        self.bridge = Bridge(uppath_chs[-1], with_shortcut=bridge_shortcut)

        if side_connect=='add':
            side_layers = []
            for  dwch, upch in zip(dwpath_chs[:-1], uppath_chs[:-1]):
                side_layers.append(Conv_Bn_ReLu(dwch,upch,1,padding=0,with_nonlinearity=False))
            self.side_layers = nn.ModuleList(side_layers)
            side_chs = uppath_chs
        else:
            self.side_layers = None
            side_chs = dwpath_chs

        up_blocks = []
        for i in range(5,0,-1):
            up_blocks.append(UpBlock(uppath_chs[i], uppath_chs[i-1], side_connect, side_chs[i-1], upsample_method))
        self.up_blocks = nn.ModuleList(up_blocks)

        self.head = nn.Conv2d(uppath_chs[0], n_classes, kernel_size=1, stride=1)


    def forward(self, x, with_output_feature_map=False):
        sides = []
        for m in self.down_blocks:
            sides.append(x)
            x = m(x)

        x = self.bridge(x)

        if self.side_layers is not None:
            for i,m in enumerate(self.side_layers):
                sides[i] = m(sides[i])

        for m, sidex in zip(self.up_blocks,sides[-1::-1]):
            x = m(x,sidex)

        x = self.head(x)
        return x


#================================================
def get_unet_res18(n_class, allres=True):
    """
    allres: all residual connect
    allres=True: 在侧向连接中都使用如 resnet 的方式，包括在bridge中加入shortcut，各层shortcut的融合中使用add而非concatenate
    allres=False: 所有侧向连接中都是原unet的方式

    """
    if allres:
        side_connect = 'add'
        bridge_shortcut = True
    else:
        side_connect = 'cat'
        bridge_shortcut = False

    res = Resnet_UNet( resnet=torchvision.models.resnet.resnet18(pretrained=True),
                       dwpath_chs = [3,    64,  64, 128, 256, 512],
                       uppath_chs = [128, 128, 128, 128, 256, 512],
                       bridge_shortcut = bridge_shortcut,
                       side_connect = side_connect,
                       upsample_method = "conv_transpose",
                       n_classes=n_class)
    return res


#================================================
def get_unet_res34(n_class, allres=True):
    """
    allres: all residual connect
    allres=True: 在侧向连接中都使用如 resnet 的方式，包括在bridge中加入shortcut，各层shortcut的融合中使用add而非concatenate
    allres=False: 所有侧向连接中都是原unet的方式

    """
    if allres:
        side_connect = 'add'
        bridge_shortcut = True
    else:
        side_connect = 'cat'
        bridge_shortcut = False

    res = Resnet_UNet( resnet=torchvision.models.resnet.resnet34(pretrained=True),
                       dwpath_chs = [3,    64,  64, 128, 256, 512],
                       uppath_chs = [128, 128, 128, 128, 256, 512],
                       bridge_shortcut = bridge_shortcut,
                       side_connect = side_connect,
                       upsample_method = "conv_transpose",
                       n_classes=n_class)
    return res


#================================================
def get_unet_res50(n_class, allres=True):
    """
    allres: all residual connect
    allres=True: 在侧向连接中都使用如 resnet 的方式，包括在bridge中加入shortcut，各层shortcut的融合中使用add而非concatenate
    allres=False: 所有侧向连接中都是原unet的方式

    """
    if allres:
        side_connect = 'add'
        bridge_shortcut = True
    else:
        side_connect = 'cat'
        bridge_shortcut = False

    res = Resnet_UNet( resnet=torchvision.models.resnet.resnet50(pretrained=True),
                       dwpath_chs = [3,   64,  256, 512, 1024, 2048],
                       uppath_chs = [128, 128, 256, 512, 1024, 2048],
                       bridge_shortcut = bridge_shortcut,
                       side_connect = side_connect,
                       upsample_method = "conv_transpose",
                       n_classes=n_class)
    return res
