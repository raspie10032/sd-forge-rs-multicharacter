import {readFile, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

const assets = new URL('../../rs_forge_mc/shared/web/pose3d/', import.meta.url);
const output = new URL('editor.bundle.mjs', assets);
await build({
    entryPoints: [fileURLToPath(new URL('editor.mjs', assets))],
    bundle: true,
    format: 'esm',
    target: 'es2022',
    minify: true,
    outfile: fileURLToPath(output),
    legalComments: 'eof',
    nodePaths: [fileURLToPath(new URL('node_modules/', import.meta.url))],
});
await writeFile(output, (await readFile(output, 'utf8')).replace(/[ \t]+$/gm, ''));
