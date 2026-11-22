/**
 * Webhook Google Apps Script (Finanças V2) — iPhone (Atalhos / Apple Pay) -> Aba `transacoes`
 *
 * Como instalar/atualizar:
 * 1. Abra sua planilha no Google Sheets -> Extensões -> Apps Script.
 * 2. Substitua o código por este arquivo inteiro.
 * 3. Defina seu TOKEN_SECRETO na linha 16 (ou em Propriedades do Script).
 * 4. Implantar -> Gerenciar implantações -> Editar (lápis) -> Versão: "Nova versão" -> Implantar.
 */

// ==================== CONFIGURAÇÕES ====================
const NOME_ABA_TRANSACOES = "transacoes";
const NOME_ABA_ORCAMENTO = "orcamento";
const NOME_ABA_REGRAS = "regras";
const TOKEN_SECRETO = "TROQUE_POR_UM_TOKEN_SECRETO_FORTE";
const FUSO_HORARIO = "America/Sao_Paulo";

const CATEGORIAS_SAIDA = [
  "Alimentação",
  "Restaurante",
  "Transporte",
  "Moradia",
  "Compras",
  "Lazer",
  "Bares",
  "Saúde",
  "Academia",
  "Barbearia",
  "Assinaturas",
  "Educação",
  "Serviços",
  "Presente",
  "Vestuário",
  "Viagem",
  "Imposto, Juros e Multa",
  "Doação",
  "Investimentos",
  "Transferência Interna",
  "Outras Saídas",
  "A Revisar"
];

const CATEGORIAS_ENTRADA = [
  "Salário",
  "Renda",
  "Rendimento",
  "Cashback",
  "Estorno",
  "Bônus",
  "Transferência Interna",
  "Outras Entradas",
  "A Revisar"
];

// ==================== ENDPOINTS ====================

function doGet(e) {
  return respostaJson({
    status: "ok",
    versao: "2.0",
    aba: NOME_ABA_TRANSACOES,
    categorias_saida: CATEGORIAS_SAIDA,
    categorias_entrada: CATEGORIAS_ENTRADA
  });
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    lock.waitLock(15000);

    const payload = lerPayload(e);
    if (!payload) {
      return respostaJson({ status: "erro", mensagem: "JSON inválido ou vazio." });
    }

    const tokenConfigurado =
      PropertiesService.getScriptProperties().getProperty("TOKEN_SECRETO") || TOKEN_SECRETO;

    if (!payload.token || String(payload.token).trim() !== String(tokenConfigurado).trim()) {
      return respostaJson({ status: "erro", mensagem: "Token inválido ou ausente." });
    }

    const valorNumerico = parseValorMonetario(payload.valor);
    if (valorNumerico === null || valorNumerico === 0) {
      return respostaJson({ status: "erro", mensagem: "Valor inválido: " + payload.valor });
    }

    const tipo = normalizarTexto(payload.tipo || "despesa");
    const ehReceita =
      tipo === "receita" || tipo === "entrada" || tipo === "credito_entrada" || tipo === "ganho";
    const valorFinal = ehReceita ? Math.abs(valorNumerico) : -Math.abs(valorNumerico);

    const descricao = String(payload.descricao || "Gasto via iPhone").trim();
    const conta = String(payload.conta || "Nubank").trim();
    const meio = normalizarMeio(payload.meio || payload.fonte || "apple_pay");
    const origemDetalhe = String(payload.origem || "iPhone").trim();

    const dataObj = parseData(payload.data);
    const dataStr = Utilities.formatDate(dataObj, FUSO_HORARIO, "yyyy-MM-dd");
    const anoMes = dataStr.substring(0, 7);
    const agoraStr = Utilities.formatDate(new Date(), FUSO_HORARIO, "yyyy-MM-dd HH:mm:ss");

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = ss.getSheetByName(NOME_ABA_TRANSACOES);
    if (!sheet) {
      return respostaJson({
        status: "erro",
        mensagem: "Aba '" + NOME_ABA_TRANSACOES + "' não encontrada. Rode a migração V2 primeiro."
      });
    }

    const lastCol = sheet.getLastColumn();
    const lastRow = sheet.getLastRow();
    const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0].map(function (h) {
      return String(h).trim();
    });

    const hash = gerarHashDedup(dataStr, valorFinal, descricao, conta);

    // 1. Proteção contra clique duplo (verifica últimas 40 linhas)
    if (lastRow > 1) {
      const qtdChecar = Math.min(lastRow - 1, 40);
      const startRow = Math.max(2, lastRow - qtdChecar + 1);
      const recentes = sheet.getRange(startRow, 1, lastRow - startRow + 1, lastCol).getValues();
      if (jaExisteHashRecente(recentes, headers, hash, dataStr, valorFinal, descricao)) {
        return respostaJson({
          status: "duplicado",
          mensagem: "⚠️ Já registrado recentemente: " + descricao + " (" + formatarBRL(valorFinal) + ")"
        });
      }
    }

    // 2. Categoria: menu 1 toque -> regras -> histórico -> "A Revisar"
    let categoria = String(payload.categoria || "").trim();
    if (!categoria) {
      categoria =
        buscarCategoriaPorRegra(ss, descricao) ||
        buscarCategoriaNoHistorico(sheet, headers, descricao) ||
        "A Revisar";
    }

    const ehTransferencia = categoria === "Transferência Interna" ? "S" : "N";
    // Lançamentos de cartão/Apple Pay entram como "provisoria" para conciliar com a fatura no fim do mês;
    // se estiver sem categoria definida, entra como "revisar".
    let status = "provisoria";
    if (categoria === "A Revisar" || !categoria) {
      status = "revisar";
    } else if (meio === "dinheiro") {
      status = "confirmada";
    }

    const id = Utilities.getUuid().replace(/-/g, "").substring(0, 12);

    const registro = {
      "id": id,
      "data": dataStr,
      "valor": Number(valorFinal.toFixed(2)),
      "descricao": descricao,
      "categoria": categoria,
      "conta": conta,
      "meio": meio,
      "origem": "iphone",
      "status": status,
      "importacao_id": "",
      "conciliada_com": "",
      "hash_dedup": hash,
      "transferencia": ehTransferencia,
      "observacao": origemDetalhe,
      "criado_em": agoraStr,
      "atualizado_em": ""
    };

    const novaLinha = headers.map(function (col) {
      return Object.prototype.hasOwnProperty.call(registro, col) ? registro[col] : "";
    });

    // Escrita segura V2: apenas appendRow no final da aba `transacoes`
    sheet.appendRow(novaLinha);

    // 3. Feedback imediato com total gasto no mês e saldo do orçamento
    const resumoMes = calcularResumoDoMes(ss, sheet, headers, anoMes, categoria);
    const emoji = valorFinal < 0 ? "💸" : "💰";
    let msg =
      emoji + " " + formatarBRL(Math.abs(valorFinal)) +
      " em " + categoria + " (" + descricao + ") salvo!" +
      " • Mês: " + formatarBRL(resumoMes.totalMes);

    if (resumoMes.restanteOrcamento !== null) {
      msg += " • Resta no orçamento: " + formatarBRL(resumoMes.restanteOrcamento);
    }

    return respostaJson({
      status: "ok",
      id: id,
      mensagem: msg,
      dados: registro
    });
  } catch (err) {
    return respostaJson({
      status: "erro",
      mensagem: "Erro no Apps Script: " + err.message
    });
  } finally {
    lock.releaseLock();
  }
}

// ==================== AUXILIARES ====================

function lerPayload(e) {
  if (!e) return null;
  if (e.postData && e.postData.contents) {
    try {
      return JSON.parse(e.postData.contents);
    } catch (err) {
      return null;
    }
  }
  if (e.parameter && Object.keys(e.parameter).length > 0) {
    return e.parameter;
  }
  return null;
}

function parseValorMonetario(valor) {
  if (typeof valor === "number") return isNaN(valor) ? null : valor;
  if (valor === null || valor === undefined) return null;

  let texto = String(valor)
    .replace(/R\$/gi, "")
    .replace(/\u00A0/g, "")
    .replace(/\s+/g, "")
    .trim();
  if (!texto) return null;

  if (texto.indexOf(",") !== -1 && texto.indexOf(".") !== -1) {
    if (texto.lastIndexOf(",") > texto.lastIndexOf(".")) {
      texto = texto.replace(/\./g, "").replace(",", ".");
    } else {
      texto = texto.replace(/,/g, "");
    }
  } else if (texto.indexOf(",") !== -1) {
    texto = texto.replace(",", ".");
  }

  const num = parseFloat(texto);
  return isNaN(num) ? null : num;
}

function parseData(dataInput) {
  if (!dataInput) return new Date();
  const texto = String(dataInput).trim();
  const isoMatch = texto.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (isoMatch) {
    return new Date(Number(isoMatch[1]), Number(isoMatch[2]) - 1, Number(isoMatch[3]), 12, 0, 0);
  }
  const brMatch = texto.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})/);
  if (brMatch) {
    return new Date(Number(brMatch[3]), Number(brMatch[2]) - 1, Number(brMatch[1]), 12, 0, 0);
  }
  const parsed = new Date(texto);
  return isNaN(parsed.getTime()) ? new Date() : parsed;
}

function normalizarTexto(texto) {
  return String(texto || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizarMeio(meioInput) {
  const m = normalizarTexto(meioInput);
  if (m.indexOf("apple") !== -1) return "apple_pay";
  if (m.indexOf("pix") !== -1) return "pix";
  if (m.indexOf("cred") !== -1 || m.indexOf("cart") !== -1) return "credito";
  if (m.indexOf("deb") !== -1) return "debito";
  if (m.indexOf("dinh") !== -1) return "dinheiro";
  return m.replace(/\s+/g, "_") || "apple_pay";
}

function gerarHashDedup(dataStr, valorFinal, descricao, conta) {
  const base =
    dataStr + "|" +
    Number(valorFinal).toFixed(2) + "|" +
    normalizarTexto(descricao) + "|" +
    normalizarTexto(conta);
  const digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_1, base);
  return digest
    .map(function (b) {
      const v = (b < 0 ? b + 256 : b).toString(16);
      return v.length === 1 ? "0" + v : v;
    })
    .join("")
    .substring(0, 16);
}

function jaExisteHashRecente(linhas, headers, hash, dataStr, valorFinal, descricao) {
  const idxHash = headers.indexOf("hash_dedup");
  const idxData = headers.indexOf("data");
  const idxValor = headers.indexOf("valor");
  const idxDesc = headers.indexOf("descricao");
  const descNorm = normalizarTexto(descricao);

  for (let i = 0; i < linhas.length; i++) {
    const r = linhas[i];
    if (idxHash !== -1 && String(r[idxHash] || "").trim() === hash) {
      return true;
    }
    if (idxData !== -1 && idxValor !== -1 && idxDesc !== -1) {
      const rData = r[idxData] instanceof Date
        ? Utilities.formatDate(r[idxData], FUSO_HORARIO, "yyyy-MM-dd")
        : String(r[idxData] || "").substring(0, 10);
      const rVal = parseValorMonetario(r[idxValor]);
      const rDesc = normalizarTexto(r[idxDesc]);
      if (rData === dataStr && rVal !== null && Math.abs(rVal - valorFinal) < 0.01 && rDesc === descNorm) {
        return true;
      }
    }
  }
  return false;
}

function buscarCategoriaPorRegra(ss, descricao) {
  const sheetRegras = ss.getSheetByName(NOME_ABA_REGRAS);
  if (!sheetRegras || sheetRegras.getLastRow() <= 1) return null;
  const dados = sheetRegras.getDataRange().getValues();
  const h = dados[0].map(function (c) { return String(c).trim(); });
  const idxPadrao = h.indexOf("padrao");
  const idxCat = h.indexOf("categoria");
  const idxAtiva = h.indexOf("ativa");
  if (idxPadrao === -1 || idxCat === -1) return null;

  const alvo = normalizarTexto(descricao);
  for (let i = 1; i < dados.length; i++) {
    if (idxAtiva !== -1 && String(dados[i][idxAtiva] || "S").toUpperCase() === "N") continue;
    const padrao = normalizarTexto(dados[i][idxPadrao]);
    const cat = String(dados[i][idxCat] || "").trim();
    if (padrao && cat && alvo.indexOf(padrao) !== -1) {
      return cat;
    }
  }
  return null;
}

function buscarCategoriaNoHistorico(sheet, headers, descricao) {
  const idxDesc = headers.indexOf("descricao");
  const idxCat = headers.indexOf("categoria");
  if (idxDesc === -1 || idxCat === -1) return null;
  const lastRow = sheet.getLastRow();
  if (lastRow <= 1) return null;

  const alvo = normalizarTexto(descricao);
  if (!alvo) return null;

  const qtd = Math.min(lastRow - 1, 500);
  const startRow = Math.max(2, lastRow - qtd + 1);
  const dados = sheet.getRange(startRow, 1, lastRow - startRow + 1, headers.length).getValues();

  for (let i = dados.length - 1; i >= 0; i--) {
    const descEx = normalizarTexto(dados[i][idxDesc]);
    const catEx = String(dados[i][idxCat] || "").trim();
    if (!catEx || catEx === "A Revisar") continue;
    if (descEx === alvo || (alvo.length >= 4 && descEx.indexOf(alvo) !== -1)) {
      return catEx;
    }
  }
  return null;
}

function calcularResumoDoMes(ss, sheet, headers, anoMesAlvo) {
  const idxData = headers.indexOf("data");
  const idxValor = headers.indexOf("valor");
  const idxTransf = headers.indexOf("transferencia");
  if (idxData === -1 || idxValor === -1) {
    return { totalMes: 0, restanteOrcamento: null };
  }

  const lastRow = sheet.getLastRow();
  let totalMes = 0;
  if (lastRow > 1) {
    const qtd = Math.min(lastRow - 1, 500);
    const startRow = Math.max(2, lastRow - qtd + 1);
    const dados = sheet.getRange(startRow, 1, lastRow - startRow + 1, headers.length).getValues();
    for (let i = 0; i < dados.length; i++) {
      const d = dados[i][idxData];
      const ym = d instanceof Date
        ? Utilities.formatDate(d, FUSO_HORARIO, "yyyy-MM")
        : String(d || "").substring(0, 7);
      if (ym !== anoMesAlvo) continue;
      if (idxTransf !== -1 && String(dados[i][idxTransf] || "N").toUpperCase() === "S") continue;
      const v = parseValorMonetario(dados[i][idxValor]);
      if (v !== null && v < 0) totalMes += Math.abs(v);
    }
  }

  let restanteOrcamento = null;
  const sheetOrc = ss.getSheetByName(NOME_ABA_ORCAMENTO);
  if (sheetOrc && sheetOrc.getLastRow() > 1) {
    const orcDados = sheetOrc.getDataRange().getValues();
    const hOrc = orcDados[0].map(function (c) { return String(c).trim(); });
    const idxMes = hOrc.indexOf("mes");
    const idxGrupo = hOrc.indexOf("grupo");
    const idxVal = hOrc.indexOf("valor");
    let teto = 0;
    for (let i = 1; i < orcDados.length; i++) {
      const m = idxMes !== -1 ? String(orcDados[i][idxMes] || "").trim() : "padrao";
      const g = idxGrupo !== -1 ? String(orcDados[i][idxGrupo] || "").trim() : "";
      if ((m === anoMesAlvo || m === "padrao") && g !== "Receita") {
        const valOrc = parseValorMonetario(orcDados[i][idxVal]);
        if (valOrc !== null && valOrc > 0) teto += valOrc;
      }
    }
    if (teto > 0) {
      restanteOrcamento = teto - totalMes;
    }
  }

  return { totalMes: totalMes, restanteOrcamento: restanteOrcamento };
}

function formatarBRL(valor) {
  return "R$ " + Number(valor).toFixed(2).replace(".", ",");
}

function respostaJson(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
