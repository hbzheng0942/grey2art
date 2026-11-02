# README 演示媒体来源 / README showcase provenance

## Grey2Art 当前三行四列 / Current three-by-four overview

每行展示一个原生玩法灰盒和三个美术画面。田园首格已补入真实 v0.2 程序化灰盒；原版仍为独立美术版本。逐格来源、版本、署名和哈希见 [catalog](../showcase/catalog.json)。

Each row shows a native gameplay greybox and three art views. Garden now includes the actual v0.2 procedural greybox; its original remains a separate art version. The catalog binds per-cell source, revision and credit.

### Hole：选定参考机位 / Selected reference camera

陶瓷小镇使用维护者选定的附件原始 PNG 字节；解码后的 RGBA 像素与历史 `process/ceramic/stage-history.png` 完全一致，PNG 编码不同。轨道科幻使用同批历史 `process/orbital/stage-history.png` 原始字节。两张美术原帧均为 `hole-lookdev-validated / case-final-v2 / baseline`，不是此前的 combined 版本。

Ceramic uses the maintainer-selected attachment unchanged. Its decoded RGBA pixels match historical `process/ceramic/stage-history.png`; the PNG encoding differs. Orbital keeps the original historical `process/orbital/stage-history.png` bytes. Both art frames belong to `hole-lookdev-validated / case-final-v2 / baseline`, with their original capture identities.

灰盒和蘑菇森林按上述历史记录补拍。四张均为 1536×1024；正交相机位置 `[-12,16,6]`、目标 `[-12,0,-8]`、`KEEP_HEIGHT`、size `19`。没有用旧图缩放或裁切来代替机位匹配。最新相机、源记录哈希与图片身份见 [camera receipt](hole-reference-camera.json)，补拍脚本为 [capture_hole_reference.gd](../showcase/capture_hole_reference.gd)。

Greybox and mushroom forest were newly captured with that recorded camera. All four frames are 1536×1024, orthographic, position `[-12,16,6]`, target `[-12,0,-8]`, `KEEP_HEIGHT`, size `19`. The overview displays these unchanged 3:2 frames in matched 3:2 windows; there is no repainting, grading or scene-object change. The receipt separates the two historical images from the two new captures.

| Image | Identity | SHA-256 | Bytes |
|---|---|---|---:|
| [hole-reference-greybox.png](hole-reference-greybox.png) | New camera replay / 同机位补拍 | 18038dfffc99197a924941bd82c61e4b5a1f57ad4990bf30e421563fc3c178bc | 310563 |
| [hole-ceramic-selected-native.png](hole-ceramic-selected-native.png) | Historical native / 历史原帧 | 021bd068e10e4931a0b4a2282c77027f00408955d8c67a28b7f81a18187188c1 | 2220902 |
| [hole-orbital-selected-native.png](hole-orbital-selected-native.png) | Historical native / 历史原帧 | 4dffff7406e9b3fefee44d8888beee91cb6f3c3ba32f41d4c65b143e8388890c | 1401032 |
| [hole-reference-mycelium.png](hole-reference-mycelium.png) | New camera replay / 同机位补拍 | 4417f837bd2570249bbcb97b668b8086231b2e4aebbdc0d0b3b6cd097541f8f0 | 995708 |

本组选图共 **4,928,205 bytes**。补拍仅复制小源码至临时 overlay，共享引用大资产；原工程未修改，导入缓存和临时用户目录已清理。既有美术与场景状态保持来源边界；选图和补拍不代表当前 Skill 重新生产美术、人工玩法／美术终验或实时性能认证。

The selected files total **4,928,205 bytes**. New captures used disposable small-source overlays with canonical asset links; original game projects remain unchanged and temporary caches/user data were removed. This selection does not establish new art production, human art/gameplay acceptance or real-time performance.

### Wander Garden：真实灰盒补拍 / Actual greybox capture

[garden-greybox-native.png](garden-greybox-native.png) 来自用户提供的 `WanderGarden-v0.2-source.zip`，压缩包 SHA-256 为 `fc32528fd1d53f01f697ea110aca37a622e57b7cb5fc794932e4e31ed03c8480`。原压缩包和完整工程不随本仓库发布。截图为 Godot 4.7.2 / OpenGL Compatibility 的真实 1280×800 原生画面，保留源码灰盒的程序化彩色模型；无 AI／Lux3D 资产，也未为对照刷灰或移除模型。[来源、相机与图片哈希记录](garden-greybox-source.json)。

The greybox frame was captured from the user-supplied `WanderGarden-v0.2-source.zip`, identified by the SHA-256 above. The archive and full project are not published here. It is an actual 1280×800 native frame from Godot 4.7.2 / OpenGL Compatibility, preserving the source's colored procedural gameplay models, without AI or Lux3D assets, recoloring or model removal. The [receipt](garden-greybox-source.json) binds source, camera and image identity.

| Image | SHA-256 | Bytes |
|---|---|---:|
| [garden-greybox-native.png](garden-greybox-native.png) | 81e39e4eb7d0eb2a26819a8bf22aef3943a1b59735e410572dc920c73280bd52 | 201400 |

11 份基础文件（`main.tscn`、9 份 `scripts/*.gd`、`tests/capture.gd`）和固定公开提交 `78ac8dadab0bdf82f1af97d967dea3a847d4da9a` 的原版 base 对应文件逐项 Git blob 相同，覆盖种植、宠物及开门逻辑。公开原版 v0.9.1 使用 `play_meadow.tscn` 与美术运行层，仍是独立美术版本，并非同一灰盒重复展示。

Eleven base files (`main.tscn`, nine `scripts/*.gd` files and `tests/capture.gd`) match the public original base file-for-file by Git blob at the pinned commit, including planting, pets and gate logic. The public original v0.9.1 runs `play_meadow.tscn` with its art runtime layer and remains a separate art version.

补拍依据公开源 `biome_capture.gd` 的谷地参考参数：玩家初始摆位 `(0, 0.1, 16)`、yaw `0`、spring `8`、pitch `-0.28`、FOV `52`；实际相机变换见收据。旧三张美术图没有完整实际相机收据；小屋和植被在美术制作中重排，保留这些真实版本差异，不声称严格逐像素对齐。本次仅核实原生启动和静帧截图，未验证五区通关、性能或人工接受。

The new capture follows the source `biome_capture.gd` meadow reference recipe above. Earlier art frames lack complete actual camera receipts, and cabins and vegetation were rearranged during art production. These version differences are preserved; strict pixel alignment is not claimed. This check covers native startup and still capture only, not five-region completion, performance or human acceptance.

### Other source frames and footage / 其他源图与短片

Train uses four inspected, byte-identical original thumbnails from the public showcase project: greybox, clay, pixel V2 and H07. Source commit `0986dc2cfec6a7b21e0e257c83ec1b62fd960ebb`; copied bytes total **1,304,666**. The prior Garden originals are reused. Canonical source paths/hashes appear in the catalog. Unselected oblique close-up copies created in this task were removed; their originals stay in the owning project.

列车四图为原字节副本，田园复用已保存的三张原图。仅保留最终选用的新媒体，原工程和历史已发布图不删除。两段 12 秒列车预览为既有原片的转码节选，来源、参数和哈希见 [video sources](grey2art-video-sources.json)；离线原生录制不证明实时帧率，全部风格的匹配视频尚未齐备。

Source projects: [editable showcases](https://github.com/hbzheng0942/greybox-to-multistyle-art-showcases), by its contributors and publisher hbzheng0942; [Wander Garden](https://github.com/xuanyuc1999-ops/wander-garden-demos), by xuanyuc1999-ops. Games and media retain their own rights. The maintainer authorized these curated images and silent clips for Grey2Art documentation; source media and game assets are not relicensed under MIT.

Earlier published media provenance is retained below for existing links and release traceability.

### Continuous README loops / 首页连续动作

The two GIFs below reuse existing native recordings. Train places the full greybox frame on the left and H07 on the right, with approximate action matching. Hole shows one continuous ceramic automatic-route segment. No game frame is cropped, repainted or labelled; only full-frame scaling, GIF color quantization and frame reduction are applied. [Source hashes, exact transforms and decode checks](grey2art-motion-sources.json).

两条 GIF 复用既有原生录制：列车左侧为灰盒、右侧为 H07，动作近似匹配；Hole 为陶瓷小镇的一段连续自动路线。游戏帧仅全帧缩放、GIF 调色板量化和减帧，没有裁切、补绘、叠字或插帧。它们展示实际原生动作，不证明实时帧率或人工试玩验收。

| Loop | Size / duration | Bytes | SHA-256 |
|---|---|---:|---|
| [Train greybox + H07](train-greybox-halloween-motion.gif) | 768×216 · 8.00 s · 80 frames | 3808929 | `b1547d4fead57a00dc809b6fc73f789fa5fb931ed7348366991eede33e29fe14` |
| [Hole ceramic](hole-ceramic-motion.gif) | 480×270 · 7.01 s · 56 frames | 3923624 | `01120b24665f5883707c5e4e329b5e0f34ba3765c58a5fe5994739dfb0e8793a` |

Total new GIF bytes: **7,732,553**. Both files fully decode with no error or consecutive duplicate decoded frames. Representative final frames were opened and inspected. Train uses the existing small MP4 previews; Hole reads its canonical source without copying the 73.7 MB original. No engine project or large asset was copied. Offline native rendering, human acceptance and runtime performance retain the source records' separate boundaries.

## 原始案例画面 / Original source frames

首页选用三组：Hole 灰盒与三风格、Train Parkour 相应站区三风格、漫野田园同机位三版本。所有选中图片均已实际打开检查，按原始字节保存，不裁剪、调色、重绘或补帧。九张新增图片共 **5,100,373 bytes**；已有灰盒图直接复用。没有复制模型、游戏工程、构建、缓存或私人账本，也没有新录制游戏。

The homepage uses three groups: Hole greybox and three styles, matching Train Parkour station views, and three Wander Garden versions. Each selected image was opened for pixel inspection and copied byte-for-byte, without cropping, grading, repainting or frame synthesis. Nine new images total **5,100,373 bytes**; the existing greybox image is reused. No game projects, models, builds, caches or private ledgers were copied, and no new gameplay was recorded.

下列来源标识相对于各自拥有工程，是来源导航，不是本仓库内的资源路径；不包含作者电脑的绝对路径。图像固定字节，不随另一个聊天后续打包或源码更新自动变化。

Source identifiers below are relative to their owning projects, not resource paths inside this repository. The copied image bytes stay fixed if those projects later change.

| 本仓库图片 / File | 原始来源逻辑标识 / Source identifier | 固定版本 / Version | 字节数 / Bytes |
|---|---|---|---:|
| [hole-amusement-native.png](hole-amusement-native.png) | `greybox-to-multistyle-art-showcases: games/hole/styles/amusement/preview.png` | `amusement-small-props-001` | 638392 |
| [hole-mycelium-native.png](hole-mycelium-native.png) | `greybox-to-multistyle-art-showcases: games/hole/styles/mycelium/preview.png` | `five-worlds-mycelium-001` | 607288 |
| [hole-lunar-native.png](hole-lunar-native.png) | `greybox-to-multistyle-art-showcases: games/hole/styles/lunar/preview.png` | `five-worlds-lunar-001` | 411930 |
| [train-pixel-v2-station.png](train-pixel-v2-station.png) | `train-parkour: docs/qa/evidence/pixel-v2-route-finish/coverage/main/station_start.png` | Pixel Skyline V2 · route-finish | 226244 |
| [train-odd-logistics-station.jpg](train-odd-logistics-station.jpg) | `train-parkour: art/train-parkour/shared/reviews/2026-10-29-b2-full-scene/capture-18-vulkan/images/track-station_start.jpg` | B2 · capture-18-vulkan | 184068 |
| [train-halloween-station.png](train-halloween-station.png) | `train-parkour: local/h07-train-readability-20261030/capture-train-main-after02/track-station_start.png` | H07 · city08 + T2 · after02 | 1123843 |
| [garden-original-native.png](garden-original-native.png) | `wander-garden-demos: demos/01-original/previews/regions/0-meadow.png` | `78ac8dadab0bdf82f1af97d967dea3a847d4da9a` | 619404 |
| [garden-ink-native.png](garden-ink-native.png) | `wander-garden-demos: demos/02-ink-storybook/previews/regions/0-meadow.png` | 同一提交 / same commit | 638861 |
| [garden-halloween-native.png](garden-halloween-native.png) | `wander-garden-demos: demos/03-halloween/previews/regions/0-meadow.png` | 同一提交 / same commit | 650343 |

原图与本仓库副本的 SHA-256 一致 / Source and copied bytes have the same SHA-256:

```text
a63b11c7ef21db72fe7fce3f98f1e3d3e0bcba30d1a6d76a8dc4575417aa31da  hole-amusement-native.png
ec5c16c804c874577048c8069376ce32b182da5d0a4d78f5aefb7bede29bc5e4  hole-mycelium-native.png
5b34cbc20614a7d08f7a117bf151078a9a2e42697d55fbd4945fe456fd94c937  hole-lunar-native.png
761d03ab5f4aed47953d0006365321a8d8732268254f05378dfe4aa97ca69f32  train-pixel-v2-station.png
70c61272797a7524b4c85ff85f583b856b22627a36be35723fe2cd17e0cf117b  train-odd-logistics-station.jpg
14e2ca44e883353c6beafd7bd2698c86cf8f6af382a0d4295034f1d69fa4c4e6  train-halloween-station.png
c29fd0d63fa2b4ad29ccb87fee4660a92b571bc2ab1853555dff460a346ad727  garden-original-native.png
aa269a518edc7ef68d6cba71fdeb65e1c706ebe014a7c2cb7a8be59472f4603a  garden-ink-native.png
a4a64479905a00357b6bec306cd93c1dc64f8c4e7f89dc1fcca8dcf94204f30b  garden-halloween-native.png
```

Hole 三张美术图为 960×600、相同视角；原有灰盒图为 1280×800，裁框与渲染设置不同，不作逐像素对齐声明。新图来自固定开发候选的历史原生预览，采集时间未从文件 mtime 推定。Train 三图为 1440×810，对应各版本 `station_start` 玩法机位；冻结路线与相机契约的验证记录留在原工程。漫野田园三图为 1280×800 的谷地场景，原版已有美术，因此标为风格改造。

Hole art views share a 960×600 viewpoint; the earlier 1280×800 greybox crop differs, so no pixel-aligned comparison is claimed. These are historical native previews of fixed development candidates; capture times are not inferred from file modification times. Train views are 1440×810 `station_start` gameplay captures; source route/camera evidence remains in the owning project. Wander Garden uses three 1280×800 meadow views and is labeled style revision because its original already has art.

这些画面展示已有工程，不冒充本轮 Skill 版本重新生产或人工终验。Hole／Train 的公开工程包仍由独立任务准备；美术、性能及人工接受保持原记录边界。漫野田园的试玩／下载与验证范围由来源仓库维护。

These frames show existing projects, not new production or human acceptance for this Skill release. Hole/Train project publication is being prepared separately. Their art, performance and human acceptance retain the source records' limits; Wander Garden maintains its own downloads and verification scope.

## 外部案例与署名 / External examples and attribution

- [漫野田园 / Wander Garden](https://github.com/xuanyuc1999-ops/wander-garden-demos)，作者 / author [xuanyuc1999-ops](https://github.com/xuanyuc1999-ops)，选图来源固定提交 `78ac8dadab0bdf82f1af97d967dea3a847d4da9a`。原始预览直接从该提交获取，未下载完整游戏包。
- [Playable Game Gallery](https://github.com/shencaiyiyi11-byte/playable-game-gallery)，作者 / author [shencaiyiyi11-byte](https://github.com/shencaiyiyi11-byte)，[浏览器试玩 / browser demos](https://shencaiyiyi11-byte.github.io/playable-game-gallery/)。内容核对与竞速截图比较使用 `3ed4658b1a8e61df961c9d2a36ca3662827e33af`；该较早迭代仅保留链接；当前九宫格与本地录制来源见下文。

README 案例仅用于演示画面、署名和试玩／工程链接，独立于 Skill 安装与验证。用户授权精选截图展示；游戏、模型、音乐、字体及媒体保留来源项目各自权利，Skill 的 MIT 许可不对其重新授权。仅授权本项目精选展示，不额外授予游戏和媒体的再分发权利。

The linked projects provide showcase media and links, independently of Skill installation and validation. Curated screenshot display was requested by the maintainer. Games, models, music, fonts and media retain their source rights; the Skill's MIT license does not relicense them. This display does not grant additional redistribution rights for the games or their media.

## Bilingual workflows and layout — 2026-11-02

The overview and localized case sheets use fixed per-game frame ratios (Hole 3:2, Train 16:9, Garden 8:5). Cover fitting avoids edge gaps without stretching. Original source files are unchanged. Sources, generators and output identities are bound by [overview](grey2art-overview-sources.json), [case sheets](grey2art-case-sources.json) and [workflow](grey2art-workflow-cases-sources.json) receipts.

Hole has three equal 3:2 process frames followed by six other native styles in two rows of three: amusement, lunar, coral, papercraft, saffron and snack. All nine windows have the same dimensions; the source camera and full source frames are preserved.

Train uses nine equal 3:2 stages: greybox, multiscene concepts, spatial recipe, assembly design, asset board, 3D asset, P8 assembled slice, P21 playable result and pixel-style expansion. Rough native geometry was used for spatial checks before asset production; it is no longer a separate figure tile. The recipe and station-layout diagrams are reconstructed from actual recipe, design and instance records; they are explanatory views, not original historical screenshots or a measured reconstruction of the entire level. The original world-design proposal retains its uncalibrated status in the source. The asset board curates four actual modeling references with their production roles; it is not a collection of finished-model renders.

Gameplay images are proportionally cropped at the sides. The selected terrace-garden-house asset uses an actual pure-white Blender render, with larger soft lights and reduced display specular contribution. Geometry, source materials and textures are unchanged. The source, lighting recipe and output identities are recorded in [model provenance](workflow-train-clay-model-preview.json). The former torn-door station model was a rejected source candidate and is excluded from the current figures.

The [gameplay comparison](train-greybox-halloween-motion.gif) and its two original videos are again linked from the homepage; their unchanged source/capture identities remain in [motion provenance](grey2art-motion-sources.json).

## Current game/style gallery — 2026-10-31 / 当前九宫格

[Gallery catalog](../showcase/gallery.json) binds nine distinct game/style pairs across seven games to their source revisions and unchanged native frames. No pair is represented by several moments of the same recording. The gallery uses a consistent 16:10 display crop without stretching or filler; original source files retain their full dimensions. [Generator](../../scripts/render_gameplay_gallery.py) and bilingual output hashes are recorded in the catalog.

Museum uses its refined mammoth hall. Garden uses the star valley and pumpkin forest, distinct from the meadow in the comparison overview. Hole's enamel harbor uses the [selected native camera](hole-gallery-camera.json); the workflow's six other styles share the [same camera contract](hole-workflow-camera.json).

Colleague games were captured from local partial checkouts using actual native scenes and input: [stills](colleague-gallery-stills.json) and [recording](colleague-gallery-sources.json). Additional native motion previews are retained for [Night Racing](colleague-halloween-racing.gif), [Garden](gameplay-garden-ink.gif) and [Museum hall](gameplay-museum-hall.gif), with [Garden](gameplay-garden-ink-source.json) and [Museum](gameplay-museum-hall-source.json) source receipts. The Garden recording shows its meadow, not the gallery's star valley. These captures demonstrate implemented scenes and motion; they are not real-time FPS measurements or current-Skill production acceptance.
