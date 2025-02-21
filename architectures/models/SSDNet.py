import torch
import torch.nn as nn


from architectures.backbones.MobileNet import ConvBNReLU, InvertedResidual, mobilenet_v2, _make_divisible

'''
understand and implement SSD Lite for 320x320 res
'''


class OutConv(nn.Module):
    def __init__(self, in_channels, n_classes, k):
        super().__init__()
        self.k = k
        '''
        idea: adding a DWSC is cheap anyway, so might as well try to use it to 'specialize' features onto this particular output from the main stream
        '''
        self.prepare_bbox = ConvBNReLU(in_channels, in_channels, groups=in_channels)
        self.prepare_class = ConvBNReLU(in_channels, in_channels, groups=in_channels)
        # Bx(4*k)xHxW
        self.oconv1 = nn.Conv2d(in_channels, 4*k, 1)
        self.oconv2 = nn.Conv2d(in_channels, n_classes*k, 1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        return [self.flatten_conv(self.oconv1(self.prepare_bbox(x)), self.k),
                self.flatten_conv(self.sigmoid(self.oconv2(self.prepare_class(x))), self.k)]

    def flatten_conv(self, x, k):
        batch_size, channels, H, W = x.size()

        x = x.permute(0, 2, 3, 1).contiguous()  # B x H x W x (4*k)

        # batch, H*W*k, #classes or 4 (bbox coords)
        return x.view(batch_size, -1, channels//k)


class SSD_Head(nn.Module):
    def __init__(self, n_classes=3, k=6, width_mult=1):
        super().__init__()

        # intermediate lay 15 with os = 16, will be a 20x20 grid for 320x320 input, 576 is the expansion size of layer 15 in MobileNetV2
        self.out0 = OutConv(int(576 * width_mult), n_classes, k)

        # from now we use the 1280 output of the backbone, first grid 10x10
        self.out1 = OutConv(1280, n_classes, k)

        # construct second grid 5x5
        self.inv2 = InvertedResidual(inp=1280, oup=512, stride=2, expand_ratio=0.2)
        self.out2 = OutConv(512, n_classes, k)

        # third grid 3x3
        self.inv3 = InvertedResidual(inp=512, oup=256, stride=2, expand_ratio=0.25)
        self.out3 = OutConv(256, n_classes, k)

        # fourth grid 2x2
        self.inv4 = InvertedResidual(inp=256, oup=256, stride=2, expand_ratio=0.25)
        self.out4 = OutConv(256, n_classes, k)

        # last grid 1x1
        self.inv5 = InvertedResidual(inp=256, oup=64, stride=2, expand_ratio=0.5)
        self.out5 = OutConv(64, n_classes, k)

        # weight initialization
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out')
                if m.bias is not None:
                    nn.init.zeros_(m.bias)
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.ones_(m.weight)
                nn.init.zeros_(m.bias)
            elif isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, 0, 0.01)
                nn.init.zeros_(m.bias)

        self.backbone = mobilenet_v2(width_mult=width_mult)

        print('Created SSDNet model succesfully!')

    def forward(self, x):
        lay15, x = self.backbone(x)

        # 20*20*k x 4
        _20bbox, _20class = self.out0(lay15)
        _10bbox, _10class = self.out1(x)

        x = self.inv2(x)
        _5bbox, _5class = self.out2(x)

        x = self.inv3(x)
        _3bbox, _3class = self.out3(x)

        x = self.inv4(x)
        _2bbox, _2class = self.out4(x)

        x = self.inv5(x)
        _1bbox, _1class = self.out5(x)

        return [torch.cat([_20bbox, _10bbox, _5bbox, _3bbox, _2bbox, _1bbox], dim=1),
                torch.cat([_20class, _10class, _5class, _3class, _2class, _1class], dim=1)]
