import requests
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import psycopg2
from psycopg2 import pool, sql
import os
from werkzeug.utils import secure_filename
import zipfile
import shutil
from AE.modules import extractFields
import configparser
import json
import subprocess as sp
from datetime import datetime
#import telebot

app = Flask(__name__)
# Создаем пул соединений с базой данных для лучшей производительности
db_connection_pool = psycopg2.pool.SimpleConnectionPool(1, 20,host="localhost",port=5432,dbname="postgres",user="postgres",password="admin")

config = configparser.ConfigParser()
config.read('config.ini')
app.config['DEBUG'] = config.getboolean("settings","DEBUG")


#bot = telebot.TeleBot(config.get("telegram","TOKEN"))
doneProject_dir = os.path.abspath("static/doneProjects")

def download_image(url, filename):
    response = requests.get(url, stream=True)

    if response.status_code == 200:
        with open(filename, 'wb') as file:
            for chunk in response.iter_content(1024):
                file.write(chunk)
    else:
        print('Unable to download image. HTTP response code:', response.status_code)


def get_db_connection():
    # Получаем соединение с базой данных из пула
    return db_connection_pool.getconn()
def release_db_connection(conn):
    # Возвращаем соединение с базой данных в пул
    db_connection_pool.putconn(conn)
def add_row(conn, prj, pth):
    # Добавляем строку в таблицу public.project_ae
    with conn.cursor() as cur:
        cur.execute("INSERT INTO public.project_ae (imgpath, projectname) VALUES (%s, %s)", (prj, pth))
        conn.commit()
def get_images(conn):
    # Получаем все изображения из таблицы public.project_ae
    with conn.cursor() as cur:
        cur.execute("SELECT imgpath, projectname, projectpath, id FROM public.project_ae WHERE isdeleted = 'false'")
        rows = cur.fetchall()
        return [{'imgpath': row[0], 'projectname': row[1], 'projectpath': row[2], 'id': row[3]} for row in rows]
def delete_image(conn, id):
    # Удаляем изображение из таблицы public.project_ae
     with conn.cursor() as cur:
        cur.execute("UPDATE public.project_ae SET isdeleted =true WHERE id= %s", (id,))
        conn.commit()

@app.route('/', subdomain='admin')
def admin_home():
    return 'Welcome to the admin subdomain!'

@app.route('/')
def index():
    conn = get_db_connection()
    images = get_images(conn)
    release_db_connection(conn)
    # Отображаем главную страницу с изображениями
    return render_template('index.html', images=images)

#TODO отключил пока не нужно
'''@app.route('/admin')
def admin():
    conn = get_db_connection()
    images = get_images(conn)
    release_db_connection(conn)
    # Отображаем страницу администратора с изображениями
    return render_template('admin.html', images=images)
'''

@app.route('/upload')
def upload():
    # Отображаем страницу загрузки изображений
    return render_template('upload.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'success': False})
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT login, password, company, role FROM public.users WHERE login = %s AND password = %s", (username, password))
    user_data = cur.fetchone()
    release_db_connection(conn)
    if user_data:
        return jsonify({
            'success': True,
            'company': user_data[2],
            'role': user_data[3],
            'username': user_data[0]
        })
    else:
        return jsonify({'success': False})
# Настройка папки для загруженных файлов
app.config["UPLOAD_FOLDER"] = config.get('settings', 'UPLOAD_FOLDER')
app.config["PROJECTS_FOLDER"] = config.get('settings', 'PROJECTS_FOLDER')
# Убедитесь, что папки существуютE
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["PROJECTS_FOLDER"], exist_ok=True)

@app.route("/upload_zip", methods=["GET", "POST"])
def upload_zip():
    file = request.files.get("file")
    if request.method == "POST":
        if "file" not in request.files:
            return jsonify({"error": "No file part"})
        if file.filename == "":
            return jsonify({"error": "No selected file"})
        if file and file.filename.endswith(".zip"):
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], file.filename))
            archive_folder = os.path.splitext(file.filename)[0]
            return jsonify({"success": f"{archive_folder} файл загружен"})
    return jsonify({"error": "Error occurred during upload."})

@app.route('/portret', methods=['GET', 'POST'])
def portret():
    if request.method == 'POST':
        name = request.form['name']
        position = request.form['position']
        portrait = request.files['portrait']

        path_portrait = "/static/portraits"

        # Здесь добавьте код для сохранения файла изображения на сервер и получите путь до файла
        portrait.save(f".{path_portrait}/{portrait.filename}")
        image_file =f"{path_portrait}/{portrait.filename}"

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO portraits (name, position, image_file) VALUES (%s, %s, %s)",
                    (name, position, image_file))
        conn.commit()
        release_db_connection(conn)
        return redirect(url_for('index'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM portraits")
    portraits = cur.fetchall()
    release_db_connection(conn)
    return render_template('portret.html', portraits=portraits)

def extract_zip(archive_name_with_extension):
    with zipfile.ZipFile(os.path.join(app.config["UPLOAD_FOLDER"], archive_name_with_extension), "r") as zip_ref:
        zip_ref.extractall(os.path.join(app.config["PROJECTS_FOLDER"], os.path.splitext(archive_name_with_extension)[0]))

    return os.remove(os.path.join(app.config["UPLOAD_FOLDER"], archive_name_with_extension))

@app.route("/extract_zip", methods=["POST"])
def extract_zip_route():
    archive_name = request.form['archiveName']
    if archive_name:
        archive_folder = os.path.splitext(archive_name)[0]
        target_folder = os.path.join(app.config["PROJECTS_FOLDER"], archive_folder)
        os.makedirs(target_folder, exist_ok=True)

        # Добавьте расширение ".zip" к имени архива
        archive_name_with_extension = f"{archive_name}.zip"

        extract_zip(archive_name_with_extension)

        return jsonify({"success": f"{archive_folder} файл разархивирован"})

    return jsonify({"error": "Error occurred during extraction."})


@app.route('/saveTemplate', methods=['POST'])
def save_template():
    project_name = request.form['projectName']
    archive_name = request.form['archiveName']
    file = request.files['image']
    archive_name_with_extension = f"{archive_name}.zip"
    img_filename = file.filename
    img_path = os.path.join('static', 'IMG', f"{archive_name}.{file.filename.expandtabs()}")
    file.save(img_path)
# extract_zip(archive_name_with_extension)
    conn = get_db_connection()
    add_row(conn, img_path, project_name)
    release_db_connection(conn)

    return "Template saved"

@app.route('/generateFields', methods=['POST'])
def generateFields():
    archive_name = request.form['archiveName']
    projectPath = f"Projects/{archive_name}"
    fileExt = ".aep"
    findAep = [os.path.join(projectPath, _) for _ in os.listdir(os.path.join("static",projectPath)) if _.endswith(fileExt)]
    fields_html = ""
    if len(findAep)>0:

        fields_data = extractFields.generateFields(findAep[0], config.get("bat","pathAE"))


        for field in fields_data:
            field_components = field.split("/")
            comp_name = field_components[0]
            index = field_components[1]
            field_type = field_components[2]
            value = field_components[3]
            layer_name = field_components[4]

            if field_type == "Text":
                fields_html += f'<label for="{comp_name}/{index}">{layer_name}:</label><input type="text" id="{comp_name}/{index}" name="{comp_name}/{index}" value="{value}"><br>'
            elif field_type in ["Image", "Audio", "Video"]:
                fields_html += f'<label for="{comp_name}/{index}">{layer_name}:</label><input type="file" id="{comp_name}/{index}" name="{comp_name}/{index}"><br>'

    return fields_html

@app.route('/check_files_in_folder', methods=['GET'])
def get_files_in_folder():
    folder_path = "static/template"
    files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
    return jsonify(files)

@app.route("/getTables", methods=['GET'])
def getTables():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)

    tables = cur.fetchall()
    release_db_connection(conn)

    return jsonify([table[0] for table in tables])

@app.route("/getColumns", methods=['POST'])
def getColumns():
    conn = get_db_connection()
    cursor = conn.cursor()

    table_name = request.json.get('table')
    if table_name is None:
        return jsonify([])

    cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = 'public'
            AND table_name = %s
        """, (table_name,))

    columns = cursor.fetchall()
    release_db_connection(conn)

    return jsonify([column[0] for column in columns])

@app.route('/get_column_values', methods=['POST'])
def get_column_values():
    data = request.get_json()
    table = data.get('table')
    column = data.get('column')

    conn = get_db_connection()
    cursor = conn.cursor()
    query = sql.SQL("SELECT DISTINCT {} FROM {}").format(
        sql.Identifier(column),
        sql.Identifier(table)
    )
    cursor.execute(query)

    values = [row[0] for row in cursor.fetchall()]

    release_db_connection(conn)

    return jsonify(values)

@app.route('/save_fields_html', methods=['POST'])
def saveFieldsAsHTML():
    html = request.form['html']
    NameAE = request.form['nameAE']
    fileIMG = request.files['image']

    with open(f'static/template/{NameAE}.html', 'w', encoding="UTF-8") as f:
        f.write(html)

    fileIMG.save(f"static/IMG/{NameAE}.{fileIMG.filename.split('.')[1]}")

    conn = get_db_connection()
    cur = conn.cursor()
    sql = "INSERT INTO project_ae (projectname, projectpath, imgpath, isdeleted) VALUES (%s, %s, %s, %s)"
    data = (NameAE, f"static/template/{NameAE}.html",f"static/IMG/{NameAE}.{fileIMG.filename.split('.')[1]}",False)

    cur.execute(sql, data)
    conn.commit()

    release_db_connection(conn)

    return 'OK', 200
    # archive_name = request.form['archiveName']
    # templatePath = "/Projects/" + archive_name + "/"
    #
    # file = request.files['file']
    # file.save(os.path.join(templatePath, archive_name + ".html"))
    #
    # return "HTML saved"


@app.route('/deleteProject/<int:id>', methods=['POST'])
def delete_project(id):
    conn = get_db_connection()
    delete_image(conn, id)
    release_db_connection(conn)
    # Возвращаем сообщение об успешном удалении проекта
    return "Template deleted"

@app.route('/renderAE/<nameProject>',  methods=['POST'])
def renderAE(nameProject):
    texts = request.form
    files = request.files
    now = datetime.now()
    nowProjectDir=f"{doneProject_dir}/{nameProject}_{now.month}{now.day}{now.hour}{now.minute}"
    scrFile = open("static/AE_comm/scripts/renderProjectScript.js", "w", encoding="utf-8")
    if not os.path.exists(nowProjectDir):
        os.makedirs(nowProjectDir)
        
    # for file in files:
    #     if files[file].filename == "":
    #         continue
    #
    #     files[file].save(f"{nowProjectDir}/{files[file].filename}")
    #     str = "file=app.project.importFile(new ImportOptions(File('" + nowProjectDir.replace("\\", "\\\\") + "/" + \
    #           files[file].filename + "')));\nfile.name=\"Фото_" + files[file].filename + "\"\napp.project.item(" + \
    #           file.split("/")[0] + ").layer(" + file.split("/")[1] + ").replaceSource(file, false);\n"
    #     scrFile.write(str)

    for text in texts:
        value = texts[text]
        if value.startswith("http://mercator.com"):
            filename =value.rsplit("/",1)[1]
            download_image(value, f"{nowProjectDir}/{filename}")
            str = "file=app.project.importFile(new ImportOptions(File('" + nowProjectDir.replace("\\", "\\\\") + "/" + \
                  filename + "')));\nfile.name=\"Фото_" + filename + "\"\napp.project.item(" + \
                  text.split("/")[0] + ").layer(" + text.split("/")[1] + ").replaceSource(file, false);\n"
        else:
            str = "app.project.item(" + text.split("/")[0] + ").layer(" + text.split("/")[
                1] + ").property(\"Source Text\").setValue(\"" + value + "\");\n"
        scrFile.write(str)
    scrFile.write("app.project.save()\n")
    scrFile.close()

    script_dir = os.path.abspath("static")

    jsonFile = script_dir + "/AE_comm/scripts/renderProject.json"
    
    with open(jsonFile, "r") as f:
        data = json.load(f)
        data["template"]["src"] = f"file:///{script_dir}/Projects/{nameProject}/{nameProject}.aep"
        assets = data["assets"][0]
        assets["src"] = f"file:///{script_dir}/AE_comm/scripts/renderProjectScript.js"
        data["actions"]["postrender"][1]["output"] = f"{nowProjectDir}/{nameProject}.mp4"
        data["actions"]["postrender"][2]["input"] = f"{nameProject}.aep"
        data["actions"]["postrender"][2]["output"] = f"{nowProjectDir}/{nameProject}.aep"
    
    with open(jsonFile, "w") as f:
        json.dump(data, f)

    binary = config.get("bat","pathAE")
    with open(script_dir + "/AE_comm/scripts/renderProject.bat", "w") as f:
        if binary != "":
            text = f'nex.exe --file "{jsonFile}" --binary "{binary}" --skip-cleanup'
        else:
            text = f'nex.exe --file "{jsonFile}" --skip-cleanup'
        f.write(text)

    # with open(script_dir + "/AE_comm/scripts/renderProject.bat", "w") as f:
    #     text = f'nex.exe --file "{jsonFile}" --skip-cleanup'
    #     f.write(text)

    proc = sp.Popen(script_dir + "/AE_comm/scripts/renderProject.bat", cwd=f"{script_dir}/AE_comm/scripts",
                    creationflags=sp.CREATE_NEW_CONSOLE)

    stdout, stderr = proc.communicate()
    
    #return 'OK', 200
    
    #video = open(f'{pathProject}/video.mp4', 'rb')
    #bot.send_video(config.get("telegram","ChatId"), video)

    shutil.make_archive(f"{nowProjectDir}", 'zip', f"{nowProjectDir}")

    return send_file(f"{nowProjectDir}.zip", as_attachment=True), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
