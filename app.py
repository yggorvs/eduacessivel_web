import sqlite3
import csv
import io
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)
DB_NAME = "escola_gestao.db"


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def calcular_dados_academicos(aluno_row):
    """Calcula média bimestral, % de presença e status de aprovação/alerta."""
    d = dict(aluno_row)
    nota1 = float(d["nota1"])
    nota2 = float(d["nota2"])
    media = round((nota1 + nota2) / 2.0, 1)

    total_aulas = int(d["total_aulas"])
    presencas = int(d["presencas"])
    faltas = max(0, total_aulas - presencas)
    frequencia_pct = round((presencas / total_aulas) * 100.0, 1) if total_aulas > 0 else 100.0

    alerta_frequencia = frequencia_pct < 75.0
    alerta_nota = media < 5.0

    if alerta_frequencia and alerta_nota:
        status = "Alerta Crítico (Faltas <75% e Nota <5.0)"
    elif alerta_frequencia:
        status = "Alerta de Evasão (<75%)"
    elif alerta_nota:
        status = "Em Recuperação (Nota <5.0)"
    else:
        status = "Regular / Aprovado"

    d["media"] = media
    d["faltas"] = faltas
    d["frequencia_pct"] = frequencia_pct
    d["alerta_frequencia"] = alerta_frequencia
    d["alerta_nota"] = alerta_nota
    d["em_alerta"] = alerta_frequencia or alerta_nota
    d["status"] = status
    return d


def init_db():
    """Inicializa o banco SQLite3 e insere dados de demonstração caso esteja vazio."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alunos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ra TEXT NOT NULL UNIQUE,
            nome TEXT NOT NULL,
            turma TEXT NOT NULL,
            nota1 REAL NOT NULL DEFAULT 0.0,
            nota2 REAL NOT NULL DEFAULT 0.0,
            total_aulas INTEGER NOT NULL DEFAULT 20,
            presencas INTEGER NOT NULL DEFAULT 20
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comunicados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            mensagem TEXT NOT NULL,
            prioridade TEXT NOT NULL DEFAULT 'Normal',
            autor TEXT NOT NULL DEFAULT 'Secretaria Escolar',
            data_pub TEXT NOT NULL
        )
    """)

    # Popula dados iniciais para testes e gravação do vídeo se estiver vazio
    cursor.execute("SELECT COUNT(*) FROM alunos")
    if cursor.fetchone()[0] == 0:
        alunos_iniciais = [
            ("2026001", "Ana Beatriz Souza", "9º Ano A", 8.5, 9.0, 40, 38),
            ("2026002", "Bruno Henrique Lima", "9º Ano A", 6.0, 7.5, 40, 27),   # 67.5% -> Alerta <75%
            ("2026003", "Carlos Eduardo Mendes", "9º Ano B", 4.5, 4.0, 40, 35), # Média 4.3 -> Nota <5
            ("2026004", "Daniela Aparecida Rocha", "9º Ano B", 9.0, 9.5, 40, 40),
            ("2026005", "Eduardo Felipe Santos", "8º Ano A", 5.5, 6.5, 40, 26), # 65.0% -> Alerta <75%
            ("2026006", "Fernanda Cristina Oliveira", "8º Ano A", 7.5, 8.0, 40, 36)
        ]
        cursor.executemany("""
            INSERT INTO alunos (ra, nome, turma, nota1, nota2, total_aulas, presencas)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, alunos_iniciais)

    cursor.execute("SELECT COUNT(*) FROM comunicados")
    if cursor.fetchone()[0] == 0:
        comunicados_iniciais = [
            (
                "Reunião de Pais e Mestres - Fechamento Bimestral",
                "Convidamos todos os responsáveis para a reunião pedagógica de entrega de boletins e acompanhamento de frequência na próxima sexta-feira, às 19h, no auditório da escola em Suzano.",
                "Importante",
                "Coordenação Pedagógica",
                datetime.now().strftime("%d/%m/%Y %H:%M")
            ),
            (
                "Busca Ativa Escolar: Prevenção à Evasão (<75% de Presença)",
                "Solicitamos que os responsáveis pelos estudantes sinalizados com alerta de frequência compareçam à secretaria escolar para atualização cadastral e justificativa de ausências.",
                "Urgente",
                "Secretaria Escolar",
                datetime.now().strftime("%d/%m/%Y %H:%M")
            ),
            (
                "Campanha de Atualização da Carteira de Vacinação",
                "Lembramos que a cópia atualizada da caderneta de vacinação pode ser entregue digitalmente ou na secretaria até o final deste mês.",
                "Normal",
                "Direção Escolar",
                datetime.now().strftime("%d/%m/%Y %H:%M")
            )
        ]
        cursor.executemany("""
            INSERT INTO comunicados (titulo, mensagem, prioridade, autor, data_pub)
            VALUES (?, ?, ?, ?, ?)
        """, comunicados_iniciais)

    conn.commit()
    conn.close()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/indicadores", methods=["GET"])
def api_indicadores():
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM alunos").fetchall()
    conn.close()

    alunos = [calcular_dados_academicos(r) for r in rows]
    total = len(alunos)
    if total == 0:
        return jsonify({
            "total_alunos": 0,
            "media_geral": 0.0,
            "frequencia_media": 0.0,
            "alertas_evasao": 0,
            "alertas_totais": 0
        })

    media_geral = round(sum(a["media"] for a in alunos) / total, 1)
    freq_media = round(sum(a["frequencia_pct"] for a in alunos) / total, 1)
    alertas_evasao = sum(1 for a in alunos if a["alerta_frequencia"])
    alertas_totais = sum(1 for a in alunos if a["em_alerta"])

    return jsonify({
        "total_alunos": total,
        "media_geral": media_geral,
        "frequencia_media": freq_media,
        "alertas_evasao": alertas_evasao,
        "alertas_totais": alertas_totais
    })


@app.route("/api/alunos", methods=["GET", "POST"])
def api_alunos():
    conn = get_db_connection()

    if request.method == "POST":
        dados = request.get_json()
        ra = (dados.get("ra") or "").strip()
        nome = (dados.get("nome") or "").strip()
        turma = (dados.get("turma") or "").strip()
        nota1 = float(dados.get("nota1", 0.0))
        nota2 = float(dados.get("nota2", 0.0))
        total_aulas = int(dados.get("total_aulas", 20))
        presencas = int(dados.get("presencas", 20))

        if not ra or not nome or not turma:
            conn.close()
            return jsonify({"erro": "RA, Nome e Turma são obrigatórios."}), 400

        if presencas > total_aulas:
            presencas = total_aulas

        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO alunos (ra, nome, turma, nota1, nota2, total_aulas, presencas)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ra, nome, turma, nota1, nota2, total_aulas, presencas))
            conn.commit()
            novo_id = cursor.lastrowid
            novo_aluno = conn.execute("SELECT * FROM alunos WHERE id = ?", (novo_id,)).fetchone()
            conn.close()
            return jsonify(calcular_dados_academicos(novo_aluno)), 201
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({"erro": "Já existe um estudante cadastrado com este RA."}), 409

    # GET com suporte a filtros dinâmicos (RF01 / v2.0)
    busca = (request.args.get("busca") or "").strip().lower()
    turma_filtro = (request.args.get("turma") or "").strip()
    situacao_filtro = (request.args.get("situacao") or "").strip()

    rows = conn.execute("SELECT * FROM alunos ORDER BY turma, nome").fetchall()
    conn.close()

    resultado = []
    for r in rows:
        aluno = calcular_dados_academicos(r)
        if busca and (busca not in aluno["nome"].lower() and busca not in aluno["ra"].lower()):
            continue
        if turma_filtro and aluno["turma"] != turma_filtro:
            continue
        if situacao_filtro == "alerta_evasao" and not aluno["alerta_frequencia"]:
            continue
        if situacao_filtro == "alerta_geral" and not aluno["em_alerta"]:
            continue
        if situacao_filtro == "regular" and aluno["em_alerta"]:
            continue
        resultado.append(aluno)

    return jsonify(resultado)


@app.route("/api/alunos/<int:aluno_id>", methods=["PUT", "DELETE"])
def api_editar_excluir_aluno(aluno_id):
    conn = get_db_connection()
    if request.method == "DELETE":
        conn.execute("DELETE FROM alunos WHERE id = ?", (aluno_id,))
        conn.commit()
        conn.close()
        return jsonify({"mensagem": "Aluno removido com sucesso."})

    dados = request.get_json()
    nota1 = float(dados.get("nota1", 0.0))
    nota2 = float(dados.get("nota2", 0.0))
    conn.execute("""
        UPDATE alunos SET nota1 = ?, nota2 = ? WHERE id = ?
    """, (nota1, nota2, aluno_id))
    conn.commit()
    atualizado = conn.execute("SELECT * FROM alunos WHERE id = ?", (aluno_id,)).fetchone()
    conn.close()
    return jsonify(calcular_dados_academicos(atualizado))


@app.route("/api/frequencia", methods=["POST"])
def api_frequencia():
    """Registra chamada digital rápida (+ Presença ou + Falta) sem recarregar a página."""
    dados = request.get_json()
    aluno_id = dados.get("aluno_id")
    tipo = dados.get("tipo")  # 'presenca' ou 'falta'

    conn = get_db_connection()
    aluno = conn.execute("SELECT * FROM alunos WHERE id = ?", (aluno_id,)).fetchone()
    if not aluno:
        conn.close()
        return jsonify({"erro": "Aluno não encontrado."}), 404

    total_aulas = int(aluno["total_aulas"]) + 1
    presencas = int(aluno["presencas"]) + (1 if tipo == "presenca" else 0)

    conn.execute("""
        UPDATE alunos
        SET total_aulas = ?, presencas = ?
        WHERE id = ?
    """, (total_aulas, presencas, aluno_id))
    conn.commit()

    atualizado = conn.execute("SELECT * FROM alunos WHERE id = ?", (aluno_id,)).fetchone()
    conn.close()
    return jsonify(calcular_dados_academicos(atualizado))


@app.route("/api/comunicados", methods=["GET", "POST"])
def api_comunicados():
    conn = get_db_connection()

    if request.method == "POST":
        dados = request.get_json()
        titulo = (dados.get("titulo") or "").strip()
        mensagem = (dados.get("mensagem") or "").strip()
        prioridade = (dados.get("prioridade") or "Normal").strip()
        autor = (dados.get("autor") or "Secretaria Escolar").strip()

        if not titulo or not mensagem:
            conn.close()
            return jsonify({"erro": "Título e mensagem são obrigatórios."}), 400

        data_pub = datetime.now().strftime("%d/%m/%Y %H:%M")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO comunicados (titulo, mensagem, prioridade, autor, data_pub)
            VALUES (?, ?, ?, ?, ?)
        """, (titulo, mensagem, prioridade, autor, data_pub))
        conn.commit()
        novo_id = cursor.lastrowid
        novo_com = conn.execute("SELECT * FROM comunicados WHERE id = ?", (novo_id,)).fetchone()
        conn.close()
        return jsonify(dict(novo_com)), 201

    rows = conn.execute("SELECT * FROM comunicados ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/comunicados/<int:comunicado_id>", methods=["DELETE"])
def api_excluir_comunicado(comunicado_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM comunicados WHERE id = ?", (comunicado_id,))
    conn.commit()
    conn.close()
    return jsonify({"mensagem": "Comunicado excluído com sucesso."})


@app.route("/api/exportar_csv", methods=["GET"])
def api_exportar_csv():
    """Exporta relatório consolidado de frequência e boletim em CSV (compatível com Excel)."""
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM alunos ORDER BY turma, nome").fetchall()
    conn.close()

    output = io.StringIO()
    # BOM UTF-8 para abrir com acentuação correta diretamente no Microsoft Excel
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')

    writer.writerow([
        "RA", "Nome do Estudante", "Turma", "Nota 1", "Nota 2",
        "Media Bimestral", "Total de Aulas", "Presencas", "Faltas",
        "Frequencia (%)", "Situacao Academica"
    ])

    for r in rows:
        a = calcular_dados_academicos(r)
        writer.writerow([
            a["ra"], a["nome"], a["turma"],
            str(a["nota1"]).replace('.', ','),
            str(a["nota2"]).replace('.', ','),
            str(a["media"]).replace('.', ','),
            a["total_aulas"], a["presencas"], a["faltas"],
            f"{str(a['frequencia_pct']).replace('.', ',')}%",
            a["status"]
        ])

    csv_content = output.getvalue()
    output.close()

    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=relatorio_frequencia_boletim_suzano.csv"}
    )


if __name__ == "__main__":
    init_db()
    print("=================================================================")
    print(" EduAcessível Web (v2.0) - Projeto Integrador II Univesp (Suzano)")
    print(" Acesse no navegador: http://127.0.0.1:5000")
    print("=================================================================")
    app.run(host="0.0.0.0", port=5000, debug=True)