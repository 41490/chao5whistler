package video

import (
	"image"
	"image/draw"

	xdraw "golang.org/x/image/draw"
)

// ScaleToFill matches the live background rendering behavior:
// scale to cover the target canvas, then center-crop.
func ScaleToFill(src image.Image, width, height int) image.Image {
	if width <= 0 || height <= 0 {
		return src
	}
	srcBounds := src.Bounds()
	if srcBounds.Dx() == width && srcBounds.Dy() == height {
		return src
	}

	srcW := srcBounds.Dx()
	srcH := srcBounds.Dy()
	if srcW == 0 || srcH == 0 {
		return src
	}

	scaleX := float64(width) / float64(srcW)
	scaleY := float64(height) / float64(srcH)
	scale := scaleX
	if scaleY > scale {
		scale = scaleY
	}
	scaledW := int(float64(srcW) * scale)
	scaledH := int(float64(srcH) * scale)
	if scaledW < width {
		scaledW = width
	}
	if scaledH < height {
		scaledH = height
	}

	scaled := image.NewRGBA(image.Rect(0, 0, scaledW, scaledH))
	xdraw.BiLinear.Scale(scaled, scaled.Bounds(), src, srcBounds, xdraw.Over, nil)

	dst := image.NewRGBA(image.Rect(0, 0, width, height))
	offset := image.Point{
		X: (scaledW - width) / 2,
		Y: (scaledH - height) / 2,
	}
	draw.Draw(dst, dst.Bounds(), scaled, offset, draw.Src)
	return dst
}
