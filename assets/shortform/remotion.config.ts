import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');

// Cor da Fase 2 igual à do cut.mp4 (bt709, faixa limitada). Sem isto o Remotion
// grava yuvj420p, faixa CHEIA, matriz bt470bg: Y 0–255 contra 16–235 do corte, e o
// qc_final acusa "esmagado/estourado 100%" (vídeos 07 e 08, 2026-10). O bt709 do
// próprio Remotion ainda erra o croma com quadros JPEG: o zscale dele lê o JPEG
// (YCbCr bt601, faixa cheia) como se fosse bt709, e a imagem sai mais quente
// (U −1,8, V +1,0 contra o corte). A troca abaixo diz ao zscale a matriz e a faixa
// verdadeiras da entrada. Medido no vídeo 08: U/V a ±0,15 do corte, igual a
// renderizar em PNG, sem o custo de tempo do PNG.
Config.setColorSpace('bt709');
Config.overrideFfmpegCommand(({type, args}) => {
	if (type !== 'stitcher') return args;
	return args.map((arg) =>
		arg === 'zscale=matrix=709:matrixin=709:range=limited'
			? 'zscale=matrix=709:matrixin=470bg:rangein=full:range=limited'
			: arg,
	);
});

Config.overrideWebpackConfig((c) => c);
