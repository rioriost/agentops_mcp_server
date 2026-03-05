class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/b2/98/8d961cebb03d9e587e36154f678e86b068a9067d49a2db40990c93269c7e/agentops_mcp_server-0.3.1.tar.gz"
  sha256 "e946e93bb18563eaf248c3be8d9e1c124f5c9c83c724b36bd4dc422f8a93164a"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
    prefix.install "README-jp.md"
    prefix.install "docs"
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
