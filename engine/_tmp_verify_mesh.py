# -*- coding: utf-8 -*-
import glob, os
import numpy as np
uploads = os.path.join(os.getcwd(), "data", "uploads")
real = glob.glob(os.path.join(uploads, "*Custom-Dual_Color-Adaption_Board.step"))[0]

from OCP.STEPControl import STEPControl_Reader
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Tool
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_ShapeEnum
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

r = STEPControl_Reader(); r.ReadFile(real); r.TransferRoots()
shape = r.OneShape()

mesh = BRepMesh_IncrementalMesh(shape, 0.2); mesh.Perform()
exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
found = False
while exp.More() and not found:
    face = TopoDS.Face_s(exp.Current())
    loc = TopLoc_Location()
    tri = BRep_Tool.Triangulation_s(face, loc)
    if tri is not None and tri.NbTriangles() > 0:
        node1 = tri.Node(1)
        print("Node(1):", node1.X(), node1.Y(), node1.Z())
        tr = tri.Triangle(1)
        print("Triangle(1) type:", type(tr))
        got = tr.Get()
        print("Triangle.Get():", got, type(got))
        trsf = loc.Transformation()
        p = node1.Transformed(trsf)
        print("transformed node:", p.X(), p.Y(), p.Z())
        found = True
    exp.Next()

# plane area
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_SurfaceType
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
area_sum = 0.0
n_plane = 0
exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
while exp.More():
    face = TopoDS.Face_s(exp.Current())
    ad = BRepAdaptor_Surface(face)
    if ad.GetType() == GeomAbs_SurfaceType.GeomAbs_Plane:
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        area_sum += abs(props.Mass())
        n_plane += 1
    exp.Next()
print(f"plane_area total={area_sum:.1f} mm2 = {area_sum/10000:.3f} dm2 over {n_plane} planes")

# face bbox projection test
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
exp = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
while exp.More():
    face = TopoDS.Face_s(exp.Current())
    ad = BRepAdaptor_Surface(face)
    if ad.GetType() == GeomAbs_SurfaceType.GeomAbs_Cylinder:
        box = Bnd_Box()
        add_fn = getattr(BRepBndLib, "AddOptimal_s", None) or getattr(BRepBndLib, "Add_s")
        add_fn(face, box)
        xmin,ymin,zmin,xmax,ymax,zmax = box.Get()
        print(f"cyl face bbox z-range: {zmin:.2f}..{zmax:.2f} (depth={zmax-zmin:.2f})")
        break
    exp.Next()