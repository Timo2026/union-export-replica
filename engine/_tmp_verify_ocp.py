# -*- coding: utf-8 -*-
import glob, os, time
import numpy as np

uploads = os.path.join(os.getcwd(), "data", "uploads")
real = glob.glob(os.path.join(uploads, "*Custom-Dual_Color-Adaption_Board.step"))[0]
print("real:", real)

from OCP.STEPControl import STEPControl_Reader
from OCP.TopoDS import TopoDS
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopAbs import TopAbs_ShapeEnum, TopAbs_Orientation
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_SurfaceType

t0 = time.time()
reader = STEPControl_Reader()
print("ReadFile:", reader.ReadFile(real))
print("TransferRoots:", reader.TransferRoots())
shape = reader.OneShape()
print("shape null:", shape.IsNull())
print("read seconds:", round(time.time() - t0, 3))

# bbox
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
box = Bnd_Box()
add_fn = getattr(BRepBndLib, "AddOptimal_s", None) or getattr(BRepBndLib, "Add_s")
add_fn(shape, box)
xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
print(f"bbox: {xmin:.2f},{ymin:.2f},{zmin:.2f} -> {xmax:.2f},{ymax:.2f},{zmax:.2f}")
print(f"dims: {xmax-xmin:.2f} x {ymax-ymin:.2f} x {zmax-zmin:.2f}")

# face traversal
face_count = 0
cyl = 0
torus = 0
plane = 0
other = 0
exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
types = {}
while exp.More():
    face = TopoDS.Face_s(exp.Current())
    ad = BRepAdaptor_Surface(face)
    t = ad.GetType()
    types[t] = types.get(t, 0) + 1
    face_count += 1
    if t == GeomAbs_SurfaceType.GeomAbs_Cylinder:
        cyl += 1
    elif t == GeomAbs_SurfaceType.GeomAbs_Torus:
        torus += 1
    elif t == GeomAbs_SurfaceType.GeomAbs_Plane:
        plane += 1
    else:
        other += 1
    exp.Next()
print(f"face_count={face_count} cyl={cyl} torus={torus} plane={plane} other={other}")
print("types:", dict(types))

# test cylinder extraction
exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
n_cyl_test = 0
while exp.More() and n_cyl_test < 5:
    face = TopoDS.Face_s(exp.Current())
    ad = BRepAdaptor_Surface(face)
    if ad.GetType() == GeomAbs_SurfaceType.GeomAbs_Cylinder:
        cyl_surf = ad.Cylinder()
        r = cyl_surf.Radius()
        axis = cyl_surf.Axis()
        d = axis.Direction()
        print(f"cyl r={r:.3f} axis_dir=({d.X():.3f},{d.Y():.3f},{d.Z():.3f}) orient={face.Orientation()}")
        n_cyl_test += 1
    exp.Next()

# test torus
exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
n_tor_test = 0
while exp.More() and n_tor_test < 3:
    face = TopoDS.Face_s(exp.Current())
    ad = BRepAdaptor_Surface(face)
    if ad.GetType() == GeomAbs_SurfaceType.GeomAbs_Torus:
        tsurf = ad.Torus()
        print(f"torus MajorR={tsurf.MajorRadius():.3f} MinorR={tsurf.MinorRadius():.3f}")
        n_tor_test += 1
    exp.Next()

# test triangulation + solid classifier
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location
mesh = BRepMesh_IncrementalMesh(shape, 0.2)
mesh.Perform()
vtot = 0
ttot = 0
exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
while exp.More():
    face = TopoDS.Face_s(exp.Current())
    loc = TopLoc_Location()
    tri = BRep_Tool.Triangulation_s(face, loc)
    if tri is not None:
        vtot += tri.NbNodes()
        ttot += tri.NbTriangles()
    exp.Next()
print(f"mesh: vertices_total={vtot} tris_total={ttot}")

from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_State
clf = BRepClass3d_SolidClassifier()
clf.Load(shape)
cx = (xmin+xmax)/2; cy=(ymin+ymax)/2; cz=(zmin+zmax)/2
p = gp_Pnt(cx, cy, cz)
clf.Perform(p, 0.01)
st = clf.State()
print(f"center point state={st} IN={TopAbs_State.TopAbs_IN} OUT={TopAbs_State.TopAbs_OUT} ON={TopAbs_State.TopAbs_ON}")
print("total seconds:", round(time.time() - t0, 3))