---
name: explain-ladder
description: Karpathy 的四層階梯（2026-10-02）——讓 AI 的產出更好懂：寫作（ASD-STE100 做到八成）→ 圖解（Mermaid 流程／結構／比較圖）→ 網頁（可以拉、可以點的 HTML）→ 影片（客製解說片）。Use when explaining something to the user or to someone else (a teacher, a client, a teammate), when turning notes, a course, a method or a technical result into a document, a diagram, an interactive page or an explainer video, when the user says an answer is hard to read / too long, or asks to "write it plainly", "draw it", "make it a page" or "make a video". Pick the lowest layer that makes the reader understand fastest.
---

# 四層階梯：讓產出更好懂

> 來源：Andrej Karpathy，X 貼文，2026-10-02（https://x.com/karpathy/status/2105819303471976479）。

**一句話：AI 寫得越多，人越需要看得懂。同樣的內容，換一種形式，理解速度完全不同。**

```
4 影片   專門為這個人做的解說片        花費最高
3 網頁   可以點、可以拉、可以玩        中
2 圖解   一張圖勝過一整頁字            低
1 寫作   先把字寫得白、寫得短          最低（所有層的基本功）
```

## 先選層，再動手

不是每件事都要爬到第 4 層。**選能讓對方最快懂的最低那一層。**

| 內容長什麼樣 | 用哪層 |
|---|---|
| 一個答案、一個結論、一個判斷 | 1 寫作 |
| 有先後、有分岔、會繞回來（流程）；誰連到誰（結構）；好幾個選項一起比（比較） | 2 圖解 |
| 要自己動手試才懂的原理（拉一個數字，看結果怎麼變） | 3 網頁 |
| 要講給很多人聽、或要講很久；要放到平台上 | 4 影片 |

使用者指定了層（「畫成圖」「做成網頁」）就照做，不要自己往上加。
往上一層之前，下一層要先做好：網頁和影片的文字，也要守第 1 層的規則。

## 第 1 層　寫作：ASD-STE100 做到八成

ASD-STE100（簡化技術英語）是航太維修手冊的受控語言：手冊被誤讀一句，飛機就可能出事。
Karpathy 的做法是放寬一點：「做到八成」（80% of the way to ASD-STE100）。

```
一字一義   一個詞只代表一個意思；選定了就整篇不換（不要一下「板」一下「場景圖」）
句子短     步驟句最多 20 個字（中文約 25 字）；太長就切成兩句
主動句     「你打開閥門」，不說「閥門應被開啟」
步驟編號   一步一句，動作放在句首
先講結論   第一句就是答案，理由放後面
```
改寫例：
「操作人員務必確保液壓油箱於作業開始前已完成補充。」→「開始作業前，先確認油箱是滿的。」

長文可以在開頭放一張**用詞表**（詞｜在本文的意思），之後每個詞只照表用。

## 第 2 層　圖解

預設用 **Mermaid**（文字就是圖，能放進 Markdown、能改、能進 git）：
- 流程 → `flowchart`（判斷用菱形，「是／否」標在箭頭上）
- 結構 → `flowchart` 或 `classDiagram`
- 時間順序、誰對誰說話 → `sequenceDiagram`
- 比較 → 表格往往比圖好；三個以上維度才畫圖

一張圖一件事。節點文字照第 1 層：短、一字一義。
要給不會打開 Mermaid 的人看，就輸出成圖片（PNG／PDF），或放進第 3 層的網頁。

## 第 3 層　網頁：可以動手玩的說明

一個 HTML 檔，瀏覽器打開就能用，也能直接分享。適合放的互動：
- **滑桿**：拉一個數字，看結果怎麼變（最有效：自己試一次，比讀十遍記得住）
- **開關**：開／關一個條件，看差別
- **分頁**：基礎、零件、小測驗各一頁

做法：
- 這個環境有 Artifact 工具的話，照 `artifact-design` skill 做成可分享的頁面；否則寫成單一 HTML 檔、用 `open` 打開
- 字照第 1 層；圖照第 2 層（可以直接嵌 Mermaid）
- 手機寬度也要能看

## 第 4 層　影片：客製解說片

Karpathy 最看好的一層：「針對任何主題，當場做一支專屬的解說片」——他說已經開始可行。
他的指令：`Create a 3b1b style video explainer on X. Use my ElevenLabs API key for audio narration.`

```
畫面   3Blue1Brown 風格的動畫（Manim）或把第 3 層的網頁錄成畫面
旁白   AI 配音（ElevenLabs、MiniMax speech，或本機免費的 TTS）；稿子先照第 1 層寫好
長度   3 分鐘以內為原則
```
⚠️ 這層最花錢、最花時間：開始前先跟使用者確認長度、配音用哪家、費用。
（我們自己的影片管線是 MiniMax H3，偏劇情；解說片優先用 Manim 或錄網頁，比較準、比較便宜。）

## 我們做過的例子

`~/sides/短影音流量變現/` 就是一次爬了三層：
`1_寫作_短影音流量變現方法.md`（第 1 層，ASD-STE100 八成）→ `2_圖解_流程圖.md`（第 2 層）→ `3_網頁_互動教學.html`（第 3 層）

## Karpathy 的結論（給讀者的理由）

- AI 會自己做掉越來越多實際的工作；人的工作往上移，變成監督和理解。
- 智慧和程式碼越來越便宜：可以請 AI 做大型、客製、用完就丟的東西（網頁、解說片），以前根本不划算。放膽去試。
