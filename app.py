import os, sqlite3
from pathlib import Path
from functools import wraps
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parent
DB = ROOT / "alpha.db"
UPLOADS = ROOT / "static" / "uploads"
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-deployment")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
CONTACTS = [("Vincent","0118078137","Sales"),("Brenda","0187093992","Sales"),("Karen","0714954858","CEO")]
WA = os.environ.get("WHATSAPP_NUMBER", "254118078137")

def connect():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init():
    UPLOADS.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE,password_hash TEXT,role TEXT)")
        c.execute("""CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,category TEXT NOT NULL,
            description TEXT,price REAL DEFAULT 0,stock INTEGER DEFAULT 0,image TEXT,active INTEGER DEFAULT 1)""")
        if c.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            samples=[
              ("Cordless Power Drill","Power Tools","Power drill for workshop and installation tasks.",0,0,"https://images.unsplash.com/photo-1504148455328-c376907d081c?w=900&q=85"),
              ("Hand Tool Set","Hand Tools","Useful hand tools for repairs and maintenance.",0,0,"https://images.unsplash.com/photo-1581147036324-c1c6a7c6c9a5?w=900&q=85"),
              ("Construction Equipment","Construction Equipment","Equipment for building and site work.",0,0,"https://images.unsplash.com/photo-1504307651254-35680f356dfd?w=900&q=85"),
              ("Farm Sprayer","Farm Equipment","Sprayer for agricultural applications.",0,0,"https://images.unsplash.com/photo-1592982537447-7440770cbfc9?w=900&q=85"),
              ("Garden and Farm Tools","Farm Tools","Tools for garden and farm maintenance.",0,0,"https://images.unsplash.com/photo-1416879595882-3373a0480b5b?w=900&q=85"),
              ("Safety Equipment","Safety Equipment","Protective equipment for work environments.",0,0,"https://images.unsplash.com/photo-1504917595217-d4dc5ebe6122?w=900&q=85")]
            c.executemany("INSERT INTO products(name,category,description,price,stock,image) VALUES(?,?,?,?,?,?)",samples)
        email=os.environ.get("ADMIN_EMAIL","alpha2626@gmail.com").lower().strip()
        password=os.environ.get("ADMIN_PASSWORD","")
        if password and not c.execute("SELECT id FROM users WHERE email=?",(email,)).fetchone():
            c.execute("INSERT INTO users(email,password_hash,role) VALUES(?,?,?)",(email,generate_password_hash(password),"admin"))

def admin(fn):
    @wraps(fn)
    def inner(*a,**kw):
        if not session.get("admin_id"): return redirect(url_for("login",next=request.path))
        return fn(*a,**kw)
    return inner

@app.context_processor
def globals_for_templates(): return {"contacts":CONTACTS,"wa":WA}

@app.route("/")
def home():
    q=request.args.get("q","").strip(); cat=request.args.get("category","").strip()
    sql="SELECT * FROM products WHERE active=1"; args=[]
    if cat: sql+=" AND category=?"; args.append(cat)
    if q: sql+=" AND (name LIKE ? OR description LIKE ? OR category LIKE ?)"; args += [f"%{q}%"]*3
    with connect() as c:
        products=c.execute(sql+" ORDER BY id DESC",args).fetchall()
        categories=[x["category"] for x in c.execute("SELECT DISTINCT category FROM products WHERE active=1 ORDER BY category")]
    return render_template("index.html",products=products,categories=categories,q=q,cat=cat)

@app.route("/contact")
def contact(): return render_template("contact.html")

@app.route("/order/<int:pid>")
def order(pid):
    with connect() as c: p=c.execute("SELECT * FROM products WHERE id=? AND active=1",(pid,)).fetchone()
    if not p: abort(404)
    msg=f"Hello Alpha Distributors Limited, I would like to enquire about {p['name']}."
    return redirect(f"https://wa.me/{WA}?text={quote(msg)}")

@app.route("/admin/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        email=request.form.get("email","").lower().strip(); pw=request.form.get("password","")
        with connect() as c: u=c.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        if u and check_password_hash(u["password_hash"],pw):
            session.clear(); session["admin_id"]=u["id"]; session["admin_email"]=u["email"]
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.","error")
    return render_template("login.html")

@app.route("/admin/logout")
def logout(): session.clear(); return redirect(url_for("home"))

@app.route("/admin")
@admin
def dashboard():
    with connect() as c:
        products=c.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
        total=c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        low=c.execute("SELECT COUNT(*) FROM products WHERE stock<=5").fetchone()[0]
    return render_template("dashboard.html",products=products,total=total,low=low)

def image_upload():
    f=request.files.get("image")
    if not f or not f.filename: return ""
    ext=f.filename.rsplit(".",1)[-1].lower()
    if ext not in {"jpg","jpeg","png","webp"}: raise ValueError()
    name=secure_filename(f.filename); name=f"{Path(name).stem[:40]}_{os.urandom(4).hex()}.{ext}"
    f.save(UPLOADS/name); return name

@app.route("/admin/add",methods=["GET","POST"])
@admin
def add():
    if request.method=="POST":
        try:
            img=image_upload() or request.form.get("image_url","").strip()
            with connect() as c:
                c.execute("INSERT INTO products(name,category,description,price,stock,image) VALUES(?,?,?,?,?,?)",
                (request.form["name"].strip(),request.form["category"].strip(),request.form.get("description","").strip(),
                 float(request.form.get("price") or 0),int(request.form.get("stock") or 0),img))
            flash("Product added.","success"); return redirect(url_for("dashboard"))
        except (ValueError,KeyError): flash("Please check the fields and image format.","error")
    return render_template("product_form.html",p=None)

@app.route("/admin/edit/<int:pid>",methods=["GET","POST"])
@admin
def edit(pid):
    with connect() as c: p=c.execute("SELECT * FROM products WHERE id=?",(pid,)).fetchone()
    if not p: abort(404)
    if request.method=="POST":
        try:
            img=image_upload() or request.form.get("image_url","").strip() or p["image"]
            with connect() as c:
                c.execute("UPDATE products SET name=?,category=?,description=?,price=?,stock=?,image=? WHERE id=?",
                (request.form["name"].strip(),request.form["category"].strip(),request.form.get("description","").strip(),
                 float(request.form.get("price") or 0),int(request.form.get("stock") or 0),img,pid))
            flash("Product updated.","success"); return redirect(url_for("dashboard"))
        except (ValueError,KeyError): flash("Please check the fields and image format.","error")
    return render_template("product_form.html",p=p)

@app.route("/admin/delete/<int:pid>",methods=["POST"])
@admin
def delete(pid):
    with connect() as c: c.execute("DELETE FROM products WHERE id=?",(pid,))
    flash("Product deleted.","success"); return redirect(url_for("dashboard"))

if __name__=="__main__":
    init()
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
